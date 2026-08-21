from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from aiohttp import web


class WebDebug:
    SCENARIOS = {
        "live": "Live state",
        "multi_active": "3 active campaigns",
        "mixed_inventory": "Mixed inventory",
        "disconnected": "Connection loss",
        "empty": "Empty state",
    }

    def __init__(self, validate_csrf: Callable[[web.Request], None]) -> None:
        self._validate_csrf = validate_csrf
        self.scenario = "live"

    def routes(self) -> list[web.RouteDef]:
        return [web.post("/api/debug/scenario", self.set_scenario)]

    async def set_scenario(self, request: web.Request) -> web.Response:
        self._validate_csrf(request)
        payload = await request.json()
        scenario = payload.get("scenario") if isinstance(payload, dict) else None
        if scenario not in self.SCENARIOS:
            raise web.HTTPBadRequest(text="Unknown debug scenario")
        self.scenario = scenario
        return web.json_response({"ok": True})

    def apply(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.scenario != "live":
            getattr(self, f"_{self.scenario}")(state)
        state["debug"] = {
            "scenario": self.scenario,
            "scenarios": [
                {"id": key, "label": label} for key, label in self.SCENARIOS.items()
            ],
        }
        return state

    @staticmethod
    def _multi_active(state: dict[str, Any]) -> None:
        campaigns = [
            WebDebug._campaign("alpha", "Alpha Reward Track", 18, 60),
            WebDebug._campaign("bravo", "Bravo Bonus Drops", 42, 90),
            WebDebug._campaign("charlie", "Charlie Launch Week", 7, 30),
        ]
        state.update(
            status="Watching: debug_channel",
            icon="active",
            watching_channel="debug_channel",
            campaigns=campaigns,
            mining=[WebDebug._mining(campaign) for campaign in campaigns],
            channels=[WebDebug._channel(1, "debug_channel", True, True, 12840)],
        )
        state["login"].update(connected=True, status="Logged in", user_id=123456)
        state["activity"] = [
            {"time": "12:03:00", "message": "Advanced 3 active campaigns from one stream"},
            {"time": "12:02:00", "message": "Watching debug_channel"},
        ]

    @staticmethod
    def _mixed_inventory(state: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        active = WebDebug._campaign("active", "Active campaign", 24, 60)
        upcoming = WebDebug._campaign("upcoming", "Starts tomorrow", 0, 45)
        upcoming.update(
            status="upcoming",
            starts_at=(now + timedelta(days=1)).isoformat(),
            ends_at=(now + timedelta(days=8)).isoformat(),
        )
        expired = WebDebug._campaign("expired", "Expired campaign", 45, 45)
        expired.update(
            status="expired",
            starts_at=(now - timedelta(days=8)).isoformat(),
            ends_at=(now - timedelta(days=1)).isoformat(),
            finished=True,
            claimed=1,
        )
        unlinked = WebDebug._campaign("unlinked", "Account link required", 0, 30)
        unlinked.update(eligible=False, linked=False, link_url="https://www.twitch.tv/drops/inventory")
        state.update(campaigns=[active, upcoming, expired, unlinked], mining=[])

    @staticmethod
    def _disconnected(state: dict[str, Any]) -> None:
        state.update(
            status="Websocket connection lost; retrying",
            icon="error",
            watching_channel="",
            mining=[],
            channels=[
                WebDebug._channel(1, "offline_channel", False, False, None),
                WebDebug._channel(2, "pending_channel", False, False, 420, pending=True),
            ],
            websockets={0: {"status": "reconnecting", "topics": 0}},
        )
        state["login"].update(connected=False, status="Reconnecting", user_id=None)

    @staticmethod
    def _empty(state: dict[str, Any]) -> None:
        state.update(
            status="Connected",
            icon="idle",
            watching_channel="",
            mining=[],
            campaigns=[],
            channels=[],
            activity=[],
            websockets={},
        )

    @staticmethod
    def _campaign(identifier: str, name: str, minutes: int, required: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        progress = min(1, minutes / required)
        drop = {
            "id": f"drop-{identifier}",
            "name": f"{name} Drop",
            "status": "in_progress" if minutes else "not_started",
            "starts_at": (now - timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=6)).isoformat(),
            "current_minutes": minutes,
            "required_minutes": required,
            "progress": progress,
            "benefits": [
                {
                    "name": f"{name} Reward",
                    "image_url": "/icons/pickaxe.png",
                    "type": "UNKNOWN",
                }
            ],
        }
        return {
            "id": f"campaign-{identifier}",
            "name": name,
            "game": "Debug Arena",
            "image_url": "/icons/pickaxe.png",
            "status": "active",
            "eligible": True,
            "linked": True,
            "link_url": "",
            "excluded": False,
            "finished": False,
            "starts_at": (now - timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=6)).isoformat(),
            "allowed_channels": [],
            "claimed": 0,
            "total": 1,
            "progress": progress,
            "drops": [drop],
        }

    @staticmethod
    def _mining(campaign: dict[str, Any]) -> dict[str, Any]:
        drop = campaign["drops"][0]
        remaining_minutes = drop["required_minutes"] - drop["current_minutes"]
        return {
            "channel": "debug_channel",
            "game": campaign["game"],
            "campaign": campaign["name"],
            "drop": drop["name"],
            "drop_progress": drop["progress"],
            "drop_minutes": drop["current_minutes"],
            "drop_required_minutes": drop["required_minutes"],
            "drop_remaining_seconds": remaining_minutes * 60,
            "campaign_progress": campaign["progress"],
            "campaign_remaining_minutes": remaining_minutes,
            "campaign_remaining_seconds": remaining_minutes * 60,
            "campaign_total_minutes": drop["required_minutes"],
            "image_url": campaign["image_url"],
        }

    @staticmethod
    def _channel(
        identifier: int,
        name: str,
        online: bool,
        watching: bool,
        viewers: int | None,
        *,
        pending: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": identifier,
            "name": name,
            "online": online,
            "pending": pending,
            "game": "Debug Arena",
            "viewers": viewers,
            "drops_enabled": True,
            "acl_based": False,
            "watching": watching,
        }
