import asyncio
import os
import socket
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiohttp
from yarl import URL

from constants import PriorityMode, State
from channel import Channel
from inventory import DropsCampaign
from twitch import Twitch
from web_gui import WebGUIManager, _Progress


class _Value:
    def __init__(self, value=None):
        self.value = value

    def get_with_default(self, default):
        return self.value if self.value is not None else default


class _Settings:
    def __init__(self):
        self.priority = []
        self.exclude = set()
        self.priority_mode = PriorityMode.PRIORITY_ONLY
        self.proxy = URL()
        self.mining_enabled = True
        self.enable_badges_emotes = False
        self.mine_unlinked_campaigns = False
        self.available_drops_check = False
        self.ntfy_server = "https://ntfy.sh"
        self.ntfy_topic = ""
        self.ntfy_token = ""
        self.ntfy_enabled = False
        self.saved = False

    def save(self):
        self.saved = True


class _Twitch:
    def __init__(self):
        self.settings = _Settings()
        self.inventory = []
        self.watching_channel = _Value()
        self.state = None
        self.closed = False
        self.revoked = False

    def change_state(self, state):
        self.state = state

    def close(self):
        self.closed = True

    def get_active_campaigns(self, channel):
        return []

    async def revoke_auth(self):
        self.revoked = True
        return True


class WebGUITest(unittest.IsolatedAsyncioTestCase):
    def test_snapshot_exposes_watching_channel(self):
        twitch = _Twitch()
        twitch.watching_channel = _Value(SimpleNamespace(name="Channel"))

        self.assertEqual(
            WebGUIManager(cast(Twitch, twitch)).snapshot()["watching_channel"], "Channel"
        )

    def test_snapshot_hides_cached_login_without_authentication(self):
        gui = WebGUIManager(cast(Twitch, _Twitch()))
        gui.login.update("Logged in", 123)

        self.assertFalse(gui.snapshot()["login"]["connected"])
        self.assertIsNone(gui.snapshot()["login"]["user_id"])

    async def test_login_code_hides_existing_authentication(self):
        twitch = _Twitch()
        twitch._auth_state = SimpleNamespace(user_id=123)
        gui = WebGUIManager(cast(Twitch, twitch))

        await gui.login.ask_enter_code(URL("https://www.twitch.tv/activate"), "ABCD")

        self.assertFalse(gui.snapshot()["login"]["connected"])

    def test_public_url_overrides_the_displayed_local_address(self):
        with patch.dict(os.environ, {"WEB_PUBLIC_URL": "https://drops.example.com/"}):
            gui = WebGUIManager(cast(Twitch, _Twitch()))

        self.assertEqual(gui._public_url, "https://drops.example.com")

    def test_unlinked_override_takes_precedence_over_badge_filter(self):
        campaign = object.__new__(DropsCampaign)
        campaign._twitch = cast(
            Twitch,
            SimpleNamespace(
                settings=SimpleNamespace(
                    mine_unlinked_campaigns=True,
                    enable_badges_emotes=False,
                )
            ),
        )
        campaign.linked = False
        campaign.has_badge_or_emote = True

        self.assertTrue(campaign.eligible)

    async def test_ntfy_notification_uses_json_and_bearer_token(self):
        twitch = _Twitch()
        twitch.settings.ntfy_server = "https://notify.example.com"
        twitch.settings.ntfy_topic = "drops_private"
        twitch.settings.ntfy_token = "tk_secret"
        gui = WebGUIManager(cast(Twitch, twitch))
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        response = MagicMock(status=200)
        response.__aenter__ = AsyncMock(return_value=response)
        session.post.return_value = response

        with patch("web_gui.ClientSession", return_value=session):
            await gui.tray._publish_ntfy("Reward claimed", "Mined Drop")

        session.post.assert_called_once_with(
            "https://notify.example.com",
            json={
                "topic": "drops_private",
                "message": "Reward claimed",
                "title": "Mined Drop",
            },
            headers={"Authorization": "Bearer tk_secret"},
        )

    def test_progress_exposes_live_remaining_seconds(self):
        progress = _Progress()
        progress._deadline = 160
        with patch("web_gui.monotonic", return_value=101):
            self.assertEqual(progress.remaining_seconds(5), 299)

    def test_campaign_snapshot_contains_drop_details(self):
        twitch = _Twitch()
        gui = WebGUIManager(cast(Twitch, twitch))
        benefit = SimpleNamespace(
            name="Reward",
            image_url=URL("https://example.com/reward.png"),
            type=SimpleNamespace(value="DIRECT_ENTITLEMENT"),
        )
        drop = SimpleNamespace(
            id="drop-1",
            name="First drop",
            is_claimed=False,
            can_claim=False,
            current_minutes=30,
            required_minutes=60,
            progress=0.5,
            starts_at=datetime.now(timezone.utc),
            ends_at=datetime.now(timezone.utc),
            benefits=[benefit],
        )
        campaign = SimpleNamespace(
            id="campaign-1",
            name="Campaign",
            game=SimpleNamespace(name="Game"),
            image_url=URL("https://example.com/game.png"),
            active=True,
            upcoming=False,
            linked=True,
            link_url="",
            eligible=True,
            finished=False,
            starts_at=datetime.now(timezone.utc),
            ends_at=datetime.now(timezone.utc),
            allowed_channels=[],
            claimed_drops=0,
            total_drops=1,
            progress=0.5,
            drops=[drop],
        )

        snapshot = gui._campaign(cast(DropsCampaign, campaign))

        self.assertEqual(snapshot["drops"][0]["benefits"][0]["name"], "Reward")
        self.assertEqual(snapshot["drops"][0]["status"], "in_progress")

    def test_dashboard_lists_each_campaign_advanced_by_a_channel(self):
        twitch = _Twitch()
        gui = WebGUIManager(cast(Twitch, twitch))
        channel = cast(Channel, SimpleNamespace(name="Channel"))
        drop = SimpleNamespace(
            rewards_text=lambda: "Reward",
            name="Drop",
            progress=0.5,
            current_minutes=30,
            required_minutes=60,
            remaining_minutes=30,
        )
        campaigns = [
            SimpleNamespace(
                name=f"Campaign {number}",
                game=SimpleNamespace(name="Game"),
                first_drop=drop,
                progress=0.5,
                remaining_minutes=30,
                starts_at=datetime.now(timezone.utc),
                ends_at=datetime.now(timezone.utc),
                image_url=URL("https://example.com/game.png"),
            )
            for number in (1, 2)
        ]

        mining = gui._mining(cast(list[DropsCampaign], campaigns), channel)

        self.assertEqual([item["campaign"] for item in mining], ["Campaign 1", "Campaign 2"])

    async def test_state_and_settings_routes(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        twitch = _Twitch()
        with patch.dict(
            os.environ,
            {"WEB_HOST": "127.0.0.1", "WEB_PORT": str(port), "WEB_HOT_RELOAD": "1"},
        ):
            gui = WebGUIManager(cast(Twitch, twitch))
        gui.start()

        async with aiohttp.ClientSession() as session:
            for _ in range(50):
                try:
                    async with session.get(f"http://127.0.0.1:{port}/api/state") as response:
                        state = await response.json()
                    break
                except aiohttp.ClientConnectionError:
                    await asyncio.sleep(0.01)
            else:
                self.fail("Web GUI did not start")

            self.assertEqual(state["campaigns"], [])
            csrf_headers = {"X-CSRF-Token": state["csrf_token"]}
            async with session.get(f"http://127.0.0.1:{port}/api/ui-version") as response:
                ui_version = await response.json()
            self.assertTrue(ui_version["enabled"])
            self.assertIsInstance(ui_version["version"], int)
            async with session.get(f"http://127.0.0.1:{port}/icons/active.ico") as response:
                self.assertEqual(response.status, 200)
            async with session.get(f"http://127.0.0.1:{port}/icons/pickaxe.png") as response:
                self.assertEqual(response.status, 200)
            async with session.post(
                f"http://127.0.0.1:{port}/api/refresh",
                headers={"Origin": "https://example.com"},
            ) as response:
                self.assertEqual(response.status, 403)
            async with session.post(
                f"http://127.0.0.1:{port}/api/settings",
                headers=csrf_headers,
                json={
                    "priority": ["Game A"],
                    "exclude": ["Game B"],
                    "priority_mode": "ENDING_SOONEST",
                    "proxy": "http://proxy.example:8080",
                    "mining_enabled": False,
                    "enable_badges_emotes": True,
                    "mine_unlinked_campaigns": True,
                    "available_drops_check": True,
                    "ntfy_server": "https://notify.example.com",
                    "ntfy_topic": "drops_private",
                    "ntfy_token": "tk_secret",
                    "ntfy_enabled": True,
                },
            ) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(twitch.state, State.RESTART)
            self.assertEqual(gui.snapshot()["settings"]["ntfy_token"], "••••••••")
            activity = [entry["message"] for entry in gui.snapshot()["activity"]]
            self.assertIn("Settings: Miner turned off", activity)
            self.assertIn("Settings: Priority games added: Game A", activity)
            self.assertIn("Settings: Excluded games added: Game B", activity)

            gui.tray._send_ntfy = AsyncMock()
            async with session.post(
                f"http://127.0.0.1:{port}/api/ntfy/test",
                headers=csrf_headers,
                json={
                    "ntfy_server": "https://notify.example.com",
                    "ntfy_topic": "drops_private",
                    "ntfy_token": "••••••••",
                },
            ) as response:
                self.assertEqual(response.status, 200)
            gui.tray._send_ntfy.assert_awaited_once_with(
                "https://notify.example.com",
                "drops_private",
                "tk_secret",
                "Your ntfy notification settings are working.",
                "Twitch Drops Miner",
            )

            drop = SimpleNamespace(can_claim=True, claimed=False)

            async def claim():
                drop.claimed = True
                return True

            drop.claim = claim
            twitch.inventory = [
                SimpleNamespace(
                    id="campaign-1",
                    get_drop=lambda drop_id: drop if drop_id == "drop-1" else None,
                )
            ]
            async with session.post(
                f"http://127.0.0.1:{port}/api/campaigns/campaign-1/drops/drop-1/claim",
                headers=csrf_headers,
            ) as response:
                self.assertEqual(response.status, 200)
            self.assertTrue(drop.claimed)
            self.assertEqual(twitch.state, State.INVENTORY_FETCH)

            gui.login.update("Logged in", 123)
            async with session.post(
                f"http://127.0.0.1:{port}/api/auth/reconnect",
                headers=csrf_headers,
            ) as response:
                self.assertEqual(response.status, 200)
            self.assertTrue(twitch.revoked)
            self.assertIsNone(gui.login.user_id)

        self.assertEqual(twitch.settings.priority, ["Game A"])
        self.assertEqual(twitch.settings.exclude, {"Game B"})
        self.assertFalse(twitch.settings.mining_enabled)
        self.assertTrue(twitch.settings.enable_badges_emotes)
        self.assertTrue(twitch.settings.mine_unlinked_campaigns)
        self.assertTrue(twitch.settings.available_drops_check)
        self.assertEqual(twitch.settings.ntfy_server, "https://notify.example.com")
        self.assertEqual(twitch.settings.ntfy_topic, "drops_private")
        self.assertEqual(twitch.settings.ntfy_token, "tk_secret")
        self.assertTrue(twitch.settings.ntfy_enabled)
        self.assertTrue(twitch.settings.saved)
        gui.close()
        assert gui._server_task is not None
        await gui._server_task


class TwitchConnectionTest(unittest.IsolatedAsyncioTestCase):
    def test_active_campaigns_keeps_all_campaigns_for_the_watched_channel(self):
        channel = cast(Channel, object())
        twitch = cast(Any, object.__new__(Twitch))
        twitch.wanted_games = [object()]
        twitch.watching_channel = _Value()
        twitch.inventory = [
            SimpleNamespace(can_earn=lambda current: current is channel, remaining_minutes=20),
            SimpleNamespace(can_earn=lambda current: current is channel, remaining_minutes=10),
        ]

        self.assertEqual(twitch.get_active_campaigns(channel), twitch.inventory)
        self.assertIs(twitch.get_active_campaign(channel), twitch.inventory[1])

    async def test_revoke_auth_clears_session_and_restarts(self):
        twitch = cast(Any, object.__new__(Twitch))
        auth = SimpleNamespace(access_token="token", invalidate=Mock())
        response_context = MagicMock()
        response_context.__aenter__.return_value = SimpleNamespace(status=200)
        twitch._client_type = SimpleNamespace(CLIENT_ID="client")
        twitch.get_auth = AsyncMock(return_value=auth)
        twitch.request = Mock(return_value=response_context)
        twitch.change_state = Mock()

        self.assertTrue(await Twitch.revoke_auth(twitch))
        auth.invalidate.assert_called_once_with(delete_cookies=True)
        twitch.change_state.assert_called_once_with(State.RESTART)


class EnglishOnlyTest(unittest.TestCase):
    def test_translator_exposes_only_english_in_container_mode(self):
        from translate import Translator

        with patch.dict(os.environ, {"TDM_ENGLISH_ONLY": "1"}):
            self.assertEqual(list(Translator().languages), ["English"])


if __name__ == "__main__":
    unittest.main()
