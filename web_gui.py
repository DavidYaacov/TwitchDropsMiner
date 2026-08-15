from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
from collections import deque
from datetime import datetime
from math import ceil
from pathlib import Path
from secrets import token_urlsafe
from time import monotonic
from typing import TYPE_CHECKING, Any

from aiohttp import ClientSession, ClientTimeout, web
from yarl import URL

from constants import PriorityMode, State
from exceptions import ExitRequest
from version import __version__

if TYPE_CHECKING:
    from channel import Channel
    from inventory import DropsCampaign, TimedDrop
    from twitch import Twitch
    from utils import Game


logger = logging.getLogger("TwitchDrops")
FAVICONS = frozenset({"active", "error", "idle", "maint", "pickaxe"})
NTFY_TOKEN_MASK = "••••••••"
NTFY_TOPIC_PATTERN = re.compile(r"[A-Za-z0-9_-]{0,64}")


class _Status:
    def __init__(self) -> None:
        self.text = "Starting"

    def update(self, text: str) -> None:
        self.text = text

    def clear(self) -> None:
        self.text = ""


class _Websockets:
    def __init__(self) -> None:
        self.items: dict[int, dict[str, Any]] = {}

    def update(
        self, idx: int, status: str | None = None, topics: int | None = None
    ) -> None:
        item = self.items.setdefault(idx, {"status": "", "topics": 0})
        if status is not None:
            item["status"] = status
        if topics is not None:
            item["topics"] = topics

    def remove(self, idx: int) -> None:
        self.items.pop(idx, None)


class _Button:
    def __init__(self) -> None:
        self.state = "disabled"

    def config(self, *, state: str) -> None:
        self.state = state


class _Help:
    def __init__(self) -> None:
        self._invalidate_button = _Button()


class _Login:
    def __init__(self, manager: WebGUIManager) -> None:
        self._manager = manager
        self.status = "Logged out"
        self.user_id: int | None = None
        self.verification_uri = ""
        self.user_code = ""

    async def ask_enter_code(self, verification_uri: URL, user_code: str) -> None:
        self.verification_uri = str(verification_uri)
        self.user_code = user_code
        self._manager.print(f"Open {verification_uri} and enter code {user_code}")

    def update(self, status: str, user_id: int | None = None) -> None:
        self.status = status
        self.user_id = user_id
        if user_id is not None:
            self.verification_uri = ""
            self.user_code = ""


class _Tray:
    def __init__(self, manager: WebGUIManager) -> None:
        self._manager = manager
        self.icon = "pickaxe"

    def change_icon(self, icon: str) -> None:
        self.icon = icon

    def notify(self, message: str, title: str) -> None:
        self._manager.print(f"{title}: {message.replace(chr(10), ' ')}")
        if self._manager._twitch.settings.ntfy_enabled:
            asyncio.create_task(self._publish_ntfy(message, title))

    async def _publish_ntfy(self, message: str, title: str) -> None:
        settings = self._manager._twitch.settings
        try:
            await self._send_ntfy(
                settings.ntfy_server,
                settings.ntfy_topic,
                settings.ntfy_token,
                message,
                title,
            )
            logger.info("ntfy notification sent to topic %s", settings.ntfy_topic)
        except Exception as exc:
            logger.error("Cannot send ntfy notification: %s", exc)

    @staticmethod
    async def _send_ntfy(
        server: str, topic: str, token: str, message: str, title: str
    ) -> None:
        headers = (
            {"Authorization": f"Bearer {token}"}
            if token
            else None
        )
        async with ClientSession(timeout=ClientTimeout(total=10)) as session:
            async with session.post(
                server,
                json={"topic": topic, "message": message, "title": title},
                headers=headers,
            ) as response:
                if response.status >= 400:
                    detail = (await response.text())[:200]
                    raise RuntimeError(f"ntfy rejected the notification ({response.status}): {detail}")


class _Progress:
    ALMOST_DONE_SECONDS = 10

    def __init__(self) -> None:
        self.drop: TimedDrop | None = None
        self._deadline: float | None = None

    def display(
        self, drop: TimedDrop | None, *, countdown: bool = True, subone: bool = False
    ) -> None:
        self.drop = drop
        self._deadline = (
            monotonic() + 60
            if countdown and drop is not None and drop.remaining_minutes > 0
            else None
        )

    def start_timer(self) -> None:
        if (
            self.drop is not None
            and self.drop.remaining_minutes > 0
            and self._deadline is None
        ):
            self._deadline = monotonic() + 60

    def stop_timer(self) -> None:
        self._deadline = None

    def minute_almost_done(self) -> bool:
        return self._deadline is None or self._deadline - monotonic() <= self.ALMOST_DONE_SECONDS

    def remaining_seconds(self, minutes: int) -> int:
        if minutes <= 0:
            return 0
        if self._deadline is None:
            return minutes * 60
        seconds = min(60, max(0, ceil(self._deadline - monotonic())))
        return (minutes - (seconds < 60)) * 60 + seconds % 60


class _Channels:
    def __init__(self) -> None:
        self.items: dict[int, Channel] = {}
        self.watching_id: int | None = None
        self.selected_id: int | None = None

    def display(self, channel: Channel, *, add: bool = False) -> None:
        if add or channel.id in self.items:
            self.items[channel.id] = channel

    def remove(self, channel: Channel) -> None:
        self.items.pop(channel.id, None)
        if self.watching_id == channel.id:
            self.watching_id = None

    def clear(self) -> None:
        self.items.clear()
        self.watching_id = None
        self.selected_id = None

    def clear_watching(self) -> None:
        self.watching_id = None

    def set_watching(self, channel: Channel) -> None:
        self.items[channel.id] = channel
        self.watching_id = channel.id

    def get_selection(self) -> Channel | None:
        selected = self.items.get(self.selected_id) if self.selected_id is not None else None
        self.selected_id = None
        return selected


class _Inventory:
    async def add_campaign(self, campaign: DropsCampaign) -> None:
        return None

    def update_drop(self, drop: TimedDrop) -> None:
        return None

    def clear(self) -> None:
        return None


class WebGUIManager:
    def __init__(self, twitch: Twitch) -> None:
        self._twitch = twitch
        self._close_requested = asyncio.Event()
        self._server_task: asyncio.Task[None] | None = None
        self._host = os.environ.get("WEB_HOST", "0.0.0.0")
        try:
            self._port = int(os.environ.get("WEB_PORT", "8080"))
        except ValueError as exc:
            raise ValueError("WEB_PORT must be a number") from exc
        if not 1 <= self._port <= 65535:
            raise ValueError("WEB_PORT must be between 1 and 65535")
        self._index_path = Path(__file__).with_name("web").joinpath("index.html")
        self._icons_path = Path(__file__).with_name("icons")
        self._csrf_token = token_urlsafe(32)
        self._activity: deque[dict[str, str]] = deque(maxlen=100)
        self._games: set[str] = set()
        self._claim_lock = asyncio.Lock()

        self.status = _Status()
        self.websockets = _Websockets()
        self.help = _Help()
        self.login = _Login(self)
        self.tray = _Tray(self)
        self.progress = _Progress()
        self.channels = _Channels()
        self.inv = _Inventory()

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    def start(self) -> None:
        if self._server_task is None or self._server_task.done():
            self._server_task = asyncio.create_task(self._serve())
            self._server_task.add_done_callback(self._server_stopped)

    def _server_stopped(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Web GUI stopped: %s", error)
            self.close()

    def stop(self) -> None:
        if self._server_task is not None and not self._server_task.done():
            self._server_task.cancel()

    def close_window(self) -> None:
        return None

    def close(self, *args: Any) -> int:
        self._close_requested.set()
        self._twitch.close()
        return 0

    def prevent_close(self) -> None:
        self._close_requested.clear()

    async def wait_until_closed(self) -> None:
        await self._close_requested.wait()

    async def coro_unless_closed(self, coro: Any) -> Any:
        work = asyncio.ensure_future(coro)
        closing = asyncio.create_task(self._close_requested.wait())
        done, pending = await asyncio.wait(
            (work, closing), return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if closing in done:
            raise ExitRequest()
        return await work

    def print(self, message: str) -> None:
        print(message)
        stamp = datetime.now().astimezone().strftime("%H:%M:%S")
        for line in str(message).splitlines() or [""]:
            self._activity.appendleft({"time": stamp, "message": line})

    def save(self, *, force: bool = False) -> None:
        return None

    def grab_attention(self, *, sound: bool = True) -> None:
        return None

    def set_games(self, games: set[Game]) -> None:
        self._games.update(game.name for game in games)

    def display_drop(
        self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False
    ) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)

    def clear_drop(self) -> None:
        self.progress.display(None)

    async def _serve(self) -> None:
        app = web.Application(client_max_size=32 * 1024)
        app.add_routes(
            [
                web.get("/", self._index),
                web.get("/icons/{icon}.ico", self._favicon),
                web.get("/api/state", self._get_state),
                web.post("/api/auth/reconnect", self._reconnect),
                web.post("/api/refresh", self._refresh),
                web.post("/api/settings", self._update_settings),
                web.post("/api/ntfy/test", self._test_ntfy),
                web.post("/api/channels/{channel_id}/watch", self._watch_channel),
                web.post(
                    "/api/campaigns/{campaign_id}/drops/{drop_id}/claim",
                    self._claim_drop,
                ),
            ]
        )
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, self._host, self._port).start()
            self.print(f"Web GUI available at http://localhost:{self._port}")
            await self._close_requested.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()

    async def _index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(
            self._index_path,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'self'; img-src https: data:; "
                    "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                    "connect-src 'self'; frame-ancestors 'none'"
                ),
            },
        )

    async def _get_state(self, request: web.Request) -> web.Response:
        return web.json_response(self.snapshot(), headers={"Cache-Control": "no-store"})

    async def _favicon(self, request: web.Request) -> web.StreamResponse:
        icon = request.match_info["icon"]
        if icon not in FAVICONS:
            raise web.HTTPNotFound()
        return web.FileResponse(self._icons_path / f"{icon}.ico")

    async def _refresh(self, request: web.Request) -> web.Response:
        self._validate_csrf(request)
        self._twitch.change_state(State.INVENTORY_FETCH)
        return web.json_response({"ok": True})

    async def _reconnect(self, request: web.Request) -> web.Response:
        self._validate_csrf(request)
        if not await self._twitch.revoke_auth():
            raise web.HTTPBadGateway(text="Twitch did not revoke the current connection")
        self.login.update("Logged out", None)
        return web.json_response({"ok": True})

    async def _watch_channel(self, request: web.Request) -> web.Response:
        self._validate_csrf(request)
        try:
            channel_id = int(request.match_info["channel_id"])
        except ValueError as exc:
            raise web.HTTPBadRequest(text="Invalid channel") from exc
        if channel_id not in self.channels.items:
            raise web.HTTPNotFound(text="Channel not found")
        self.channels.selected_id = channel_id
        self._twitch.change_state(State.CHANNEL_SWITCH)
        return web.json_response({"ok": True})

    async def _claim_drop(self, request: web.Request) -> web.Response:
        self._validate_csrf(request)
        campaign = next(
            (
                campaign
                for campaign in self._twitch.inventory
                if campaign.id == request.match_info["campaign_id"]
            ),
            None,
        )
        drop = campaign.get_drop(request.match_info["drop_id"]) if campaign else None
        if drop is None:
            raise web.HTTPNotFound(text="Drop not found")
        async with self._claim_lock:
            if not drop.can_claim:
                raise web.HTTPConflict(text="Drop is not ready to claim")
            if not await drop.claim():
                raise web.HTTPBadGateway(text="Twitch did not confirm the claim")
        self._twitch.change_state(State.INVENTORY_FETCH)
        return web.json_response({"ok": True})

    async def _update_settings(self, request: web.Request) -> web.Response:
        self._validate_csrf(request)
        try:
            payload = await request.json()
        except (ValueError, TypeError) as exc:
            raise web.HTTPBadRequest(text="Expected JSON") from exc
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="Expected a JSON object")

        priority = self._game_list(payload.get("priority"), "priority")
        exclude = self._game_list(payload.get("exclude"), "exclude")
        try:
            priority_mode = PriorityMode[str(payload.get("priority_mode", ""))]
        except KeyError as exc:
            raise web.HTTPBadRequest(text="Invalid priority mode") from exc

        proxy_text = str(payload.get("proxy", "")).strip()
        proxy = URL(proxy_text)
        if proxy_text and (proxy.scheme not in ("http", "https") or proxy.host is None):
            raise web.HTTPBadRequest(text="Proxy must be an HTTP(S) URL")

        ntfy_server_text, ntfy_topic, ntfy_token = self._ntfy_config(payload)
        ntfy_enabled = self._boolean(payload.get("ntfy_enabled"), "ntfy_enabled")
        if ntfy_enabled and not ntfy_topic:
            raise web.HTTPBadRequest(text="ntfy topic is required when notifications are enabled")
        mining_enabled = self._boolean(payload.get("mining_enabled"), "mining_enabled")
        enable_badges_emotes = self._boolean(
            payload.get("enable_badges_emotes"), "enable_badges_emotes"
        )
        mine_unlinked_campaigns = self._boolean(
            payload.get("mine_unlinked_campaigns"), "mine_unlinked_campaigns"
        )
        available_drops_check = self._boolean(
            payload.get("available_drops_check"), "available_drops_check"
        )

        settings = self._twitch.settings
        changes: list[str] = []
        added_priority = [game for game in priority if game not in settings.priority]
        removed_priority = [game for game in settings.priority if game not in priority]
        added_excluded = sorted(set(exclude) - settings.exclude)
        removed_excluded = sorted(settings.exclude - set(exclude))
        if added_priority:
            changes.append(f"Priority games added: {', '.join(added_priority)}")
        if removed_priority:
            changes.append(f"Priority games removed: {', '.join(removed_priority)}")
        if not added_priority and not removed_priority and priority != settings.priority:
            changes.append(f"Priority game order changed: {', '.join(priority)}")
        if added_excluded:
            changes.append(f"Excluded games added: {', '.join(added_excluded)}")
        if removed_excluded:
            changes.append(f"Excluded games removed: {', '.join(removed_excluded)}")
        if priority_mode is not settings.priority_mode:
            changes.append(
                f"Priority mode changed: {settings.priority_mode.name} → {priority_mode.name}"
            )
        if proxy != settings.proxy:
            changes.append("Proxy changed")
        boolean_changes = (
            ("Miner", settings.mining_enabled, mining_enabled),
            ("Mine unlinked campaigns", settings.mine_unlinked_campaigns, mine_unlinked_campaigns),
            ("Badge and emote support", settings.enable_badges_emotes, enable_badges_emotes),
            ("Available-drops checks", settings.available_drops_check, available_drops_check),
            ("ntfy notifications", settings.ntfy_enabled, ntfy_enabled),
        )
        changes.extend(
            f"{name} turned {'on' if new else 'off'}"
            for name, old, new in boolean_changes
            if old != new
        )
        if ntfy_server_text != settings.ntfy_server:
            changes.append("ntfy server changed")
        if ntfy_topic != settings.ntfy_topic:
            changes.append("ntfy topic changed")
        if ntfy_token != settings.ntfy_token:
            changes.append("ntfy access token changed")

        settings.priority = priority
        settings.exclude = set(exclude)
        settings.priority_mode = priority_mode
        settings.proxy = proxy
        settings.mining_enabled = mining_enabled
        settings.enable_badges_emotes = enable_badges_emotes
        settings.mine_unlinked_campaigns = mine_unlinked_campaigns
        settings.available_drops_check = available_drops_check
        settings.ntfy_server = ntfy_server_text
        settings.ntfy_topic = ntfy_topic
        settings.ntfy_token = ntfy_token
        settings.ntfy_enabled = ntfy_enabled
        settings.save()
        for change in changes:
            self.print(f"Settings: {change}")
        self._twitch.change_state(State.RESTART)
        return web.json_response({"ok": True})

    async def _test_ntfy(self, request: web.Request) -> web.Response:
        self._validate_csrf(request)
        try:
            payload = await request.json()
        except (ValueError, TypeError) as exc:
            raise web.HTTPBadRequest(text="Expected JSON") from exc
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="Expected a JSON object")
        server, topic, token = self._ntfy_config(payload)
        if not topic:
            raise web.HTTPBadRequest(text="Enter an ntfy topic first")
        try:
            await self.tray._send_ntfy(
                server,
                topic,
                token,
                "Your ntfy notification settings are working.",
                "Twitch Drops Miner",
            )
        except Exception as exc:
            logger.error("Cannot send ntfy test notification: %s", exc)
            raise web.HTTPBadGateway(text=str(exc)) from exc
        return web.json_response({"ok": True})

    def _ntfy_config(self, payload: dict[str, Any]) -> tuple[str, str, str]:
        server_text = str(payload.get("ntfy_server", "")).strip().rstrip("/")
        server = URL(server_text)
        if (
            len(server_text) > 2048
            or server.scheme not in ("http", "https")
            or server.host is None
            or server.user is not None
            or server.query
            or server.fragment
        ):
            raise web.HTTPBadRequest(text="ntfy server must be an HTTP(S) URL")
        topic = str(payload.get("ntfy_topic", "")).strip()
        if not NTFY_TOPIC_PATTERN.fullmatch(topic):
            raise web.HTTPBadRequest(text="ntfy topic may contain letters, numbers, _ and -")
        token = str(payload.get("ntfy_token", ""))
        if len(token) > 512:
            raise web.HTTPBadRequest(text="ntfy token is too long")
        if token == NTFY_TOKEN_MASK:
            token = self._twitch.settings.ntfy_token
        return server_text, topic, token

    def _validate_csrf(self, request: web.Request) -> None:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied, self._csrf_token):
            raise web.HTTPForbidden(text="Invalid request token; reload the web page")

    @staticmethod
    def _boolean(value: Any, field: str) -> bool:
        if not isinstance(value, bool):
            raise web.HTTPBadRequest(text=f"{field} must be true or false")
        return value

    @staticmethod
    def _game_list(value: Any, field: str) -> list[str]:
        if not isinstance(value, list) or len(value) > 100:
            raise web.HTTPBadRequest(text=f"{field} must be a list")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str) or len(item) > 100:
                raise web.HTTPBadRequest(text=f"Invalid {field} game")
            item = item.strip()
            if item and item not in result:
                result.append(item)
        return result

    def snapshot(self) -> dict[str, Any]:
        twitch = self._twitch
        watching = twitch.watching_channel.get_with_default(None)
        drop = self.progress.drop
        settings = twitch.settings
        return {
            "version": __version__,
            "csrf_token": self._csrf_token,
            "commit": os.environ.get("TDM_COMMIT_SHA", "unknown"),
            "status": self.status.text,
            "icon": self.tray.icon,
            "login": {
                "status": self.login.status,
                "connected": self.login.user_id is not None,
                "user_id": self.login.user_id,
                "verification_uri": self.login.verification_uri,
                "user_code": self.login.user_code,
            },
            "mining": self._mining(drop, watching),
            "campaigns": [self._campaign(campaign) for campaign in twitch.inventory],
            "channels": [
                {
                    "id": channel.id,
                    "name": channel.name,
                    "online": channel.online,
                    "pending": channel.pending_online,
                    "game": str(channel.game or ""),
                    "viewers": channel.viewers,
                    "drops_enabled": channel.drops_enabled,
                    "acl_based": channel.acl_based,
                    "watching": channel.id == self.channels.watching_id,
                }
                for channel in self.channels.items.values()
            ],
            "websockets": self.websockets.items,
            "activity": list(self._activity),
            "settings": {
                "priority": list(settings.priority),
                "exclude": sorted(settings.exclude),
                "priority_mode": settings.priority_mode.name,
                "proxy": str(settings.proxy),
                "mining_enabled": settings.mining_enabled,
                "enable_badges_emotes": settings.enable_badges_emotes,
                "mine_unlinked_campaigns": settings.mine_unlinked_campaigns,
                "available_drops_check": settings.available_drops_check,
                "ntfy_server": settings.ntfy_server,
                "ntfy_topic": settings.ntfy_topic,
                "ntfy_token": NTFY_TOKEN_MASK if settings.ntfy_token else "",
                "ntfy_enabled": settings.ntfy_enabled,
                "games": sorted(self._games),
            },
        }

    def _mining(self, drop: TimedDrop | None, channel: Channel | None) -> dict[str, Any] | None:
        if drop is None:
            return None
        campaign = drop.campaign
        return {
            "channel": channel.name if channel is not None else "",
            "game": campaign.game.name,
            "campaign": campaign.name,
            "drop": drop.rewards_text() or drop.name,
            "drop_progress": drop.progress,
            "drop_minutes": drop.current_minutes,
            "drop_required_minutes": drop.required_minutes,
            "drop_remaining_seconds": self.progress.remaining_seconds(drop.remaining_minutes),
            "campaign_progress": campaign.progress,
            "campaign_remaining_minutes": campaign.remaining_minutes,
            "campaign_remaining_seconds": self.progress.remaining_seconds(campaign.remaining_minutes),
            "campaign_total_minutes": max(0, (campaign.ends_at - campaign.starts_at).total_seconds() / 60),
            "image_url": str(campaign.image_url),
        }

    def _campaign(self, campaign: DropsCampaign) -> dict[str, Any]:
        if campaign.active:
            status = "active"
        elif campaign.upcoming:
            status = "upcoming"
        else:
            status = "expired"
        return {
            "id": campaign.id,
            "name": campaign.name,
            "game": campaign.game.name,
            "image_url": str(campaign.image_url),
            "status": status,
            "eligible": campaign.eligible,
            "linked": campaign.linked,
            "link_url": campaign.link_url,
            "excluded": (
                campaign.game.name in self._twitch.settings.exclude
                or self._twitch.settings.priority_mode is PriorityMode.PRIORITY_ONLY
                and campaign.game.name not in self._twitch.settings.priority
            ),
            "finished": campaign.finished,
            "starts_at": campaign.starts_at.isoformat(),
            "ends_at": campaign.ends_at.isoformat(),
            "allowed_channels": [channel.name for channel in campaign.allowed_channels],
            "claimed": campaign.claimed_drops,
            "total": campaign.total_drops,
            "progress": campaign.progress,
            "drops": [WebGUIManager._drop(drop) for drop in campaign.drops],
        }

    @staticmethod
    def _drop(drop: TimedDrop) -> dict[str, Any]:
        if drop.is_claimed:
            status = "claimed"
        elif drop.can_claim:
            status = "ready"
        elif drop.current_minutes:
            status = "in_progress"
        else:
            status = "not_started"
        return {
            "id": drop.id,
            "name": drop.name,
            "status": status,
            "starts_at": drop.starts_at.isoformat(),
            "ends_at": drop.ends_at.isoformat(),
            "current_minutes": drop.current_minutes,
            "required_minutes": drop.required_minutes,
            "progress": drop.progress,
            "benefits": [
                {
                    "name": benefit.name,
                    "image_url": str(benefit.image_url),
                    "type": benefit.type.value,
                }
                for benefit in drop.benefits
            ],
        }
