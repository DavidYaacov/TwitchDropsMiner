from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from aiohttp import web


class WebDebug:
    SCENARIOS = {
        "live": "Live state",
        "custom_active": "Custom campaigns",
        "mixed_inventory": "Mixed inventory",
        "device_login": "Device login",
        "disconnected": "Connection loss",
        "empty": "Empty state",
    }

    def __init__(self, validate_csrf: Callable[[web.Request], None]) -> None:
        self._validate_csrf = validate_csrf
        self.scenario = "live"
        self.options = {
            "campaign_count": 5,
            "progress_percent": 50,
            "channel_name": "debug_channel",
            "long_labels": False,
        }

    def routes(self) -> list[web.RouteDef]:
        return [web.post("/api/debug/scenario", self.set_scenario)]

    async def set_scenario(self, request: web.Request) -> web.Response:
        self._validate_csrf(request)
        payload = await request.json()
        scenario = payload.get("scenario") if isinstance(payload, dict) else None
        if scenario not in self.SCENARIOS:
            raise web.HTTPBadRequest(text="Unknown debug scenario")
        if scenario == "custom_active":
            campaign_count = payload.get("campaign_count", self.options["campaign_count"])
            progress_percent = payload.get("progress_percent", self.options["progress_percent"])
            channel_name = payload.get("channel_name", self.options["channel_name"])
            long_labels = payload.get("long_labels", self.options["long_labels"])
            if type(campaign_count) is not int or not 1 <= campaign_count <= 20:
                raise web.HTTPBadRequest(text="Campaign count must be between 1 and 20")
            if type(progress_percent) is not int or not 0 <= progress_percent <= 100:
                raise web.HTTPBadRequest(text="Progress must be between 0 and 100")
            if not isinstance(channel_name, str) or not 1 <= len(channel_name.strip()) <= 50:
                raise web.HTTPBadRequest(text="Channel name must be between 1 and 50 characters")
            if not isinstance(long_labels, bool):
                raise web.HTTPBadRequest(text="Long labels must be true or false")
            self.options = {
                "campaign_count": campaign_count,
                "progress_percent": progress_percent,
                "channel_name": channel_name.strip(),
                "long_labels": long_labels,
            }
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
            "options": self.options,
        }
        return state

    def _custom_active(self, state: dict[str, Any]) -> None:
        count = self.options["campaign_count"]
        progress = self.options["progress_percent"] / 100
        campaigns = []
        for index in range(1, count + 1):
            required = 30 + index % 3 * 30
            name = f"Custom Campaign {index}"
            if self.options["long_labels"]:
                name += " — Extra Long Reward Track Name for Layout Testing"
            campaigns.append(
                WebDebug._campaign(
                    f"custom-{index}", name, round(required * progress), required
                )
            )
        WebDebug._active_campaigns(state, campaigns, self.options["channel_name"])

    @staticmethod
    def _active_campaigns(
        state: dict[str, Any],
        campaigns: list[dict[str, Any]],
        channel_name: str = "debug_channel",
    ) -> None:
        state.update(
            status=f"Watching: {channel_name}",
            icon="active",
            watching_channel=channel_name,
            campaigns=campaigns,
            mining=[WebDebug._mining(campaign, channel_name) for campaign in campaigns],
            channels=[WebDebug._channel(1, channel_name, True, True, 12840)],
        )
        state["login"].update(connected=True, status="Logged in", user_id=123456)
        state["activity"] = [
            {
                "time": "12:03:00",
                "message": f"Advanced {len(campaigns)} active campaign(s) from one stream",
            },
            {"time": "12:02:00", "message": f"Watching {channel_name}"},
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
    def _device_login(state: dict[str, Any]) -> None:
        state.update(
            status="Waiting for Twitch login",
            icon="idle",
            watching_channel="",
            mining=[],
            campaigns=[],
            channels=[],
            activity=[],
            websockets={},
        )
        state["login"].update(
            connected=False,
            status="Enter the device code",
            user_id=None,
            verification_uri="https://www.twitch.tv/activate",
            user_code="ABCD-EFGH",
        )

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
    def _mining(campaign: dict[str, Any], channel_name: str = "debug_channel") -> dict[str, Any]:
        drop = campaign["drops"][0]
        remaining_minutes = drop["required_minutes"] - drop["current_minutes"]
        return {
            "channel": channel_name,
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
