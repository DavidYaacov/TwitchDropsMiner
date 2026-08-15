import asyncio
import os
import socket
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
from yarl import URL

from constants import PriorityMode, State
from web_gui import WebGUIManager


class _Value:
    def get_with_default(self, default):
        return default


class _Settings:
    def __init__(self):
        self.priority = []
        self.exclude = set()
        self.priority_mode = PriorityMode.PRIORITY_ONLY
        self.proxy = URL()
        self.enable_badges_emotes = False
        self.available_drops_check = False
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

    def change_state(self, state):
        self.state = state

    def close(self):
        self.closed = True


class WebGUITest(unittest.IsolatedAsyncioTestCase):
    def test_campaign_snapshot_contains_drop_details(self):
        twitch = _Twitch()
        gui = WebGUIManager(twitch)
        benefit = SimpleNamespace(
            name="Reward", image_url=URL("https://example.com/reward.png"),
            type=SimpleNamespace(value="DIRECT_ENTITLEMENT"),
        )
        drop = SimpleNamespace(
            id="drop-1", name="First drop", is_claimed=False, can_claim=False,
            current_minutes=30, required_minutes=60, progress=.5,
            starts_at=datetime.now(timezone.utc), ends_at=datetime.now(timezone.utc),
            benefits=[benefit],
        )
        campaign = SimpleNamespace(
            id="campaign-1", name="Campaign", game=SimpleNamespace(name="Game"),
            image_url=URL("https://example.com/game.png"), active=True, upcoming=False,
            linked=True, link_url="", eligible=True, finished=False,
            starts_at=datetime.now(timezone.utc), ends_at=datetime.now(timezone.utc),
            allowed_channels=[], claimed_drops=0, total_drops=1, progress=.5,
            drops=[drop],
        )

        snapshot = gui._campaign(campaign)

        self.assertEqual(snapshot["drops"][0]["benefits"][0]["name"], "Reward")
        self.assertEqual(snapshot["drops"][0]["status"], "in_progress")

    async def test_state_and_settings_routes(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        twitch = _Twitch()
        with patch.dict(os.environ, {"WEB_HOST": "127.0.0.1", "WEB_PORT": str(port)}):
            gui = WebGUIManager(twitch)
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
            async with session.post(
                f"http://127.0.0.1:{port}/api/refresh",
                headers={"Origin": "https://example.com"},
            ) as response:
                self.assertEqual(response.status, 403)
            async with session.post(
                f"http://127.0.0.1:{port}/api/settings",
                json={
                    "priority": ["Game A"],
                    "exclude": ["Game B"],
                    "priority_mode": "ENDING_SOONEST",
                    "proxy": "http://proxy.example:8080",
                    "enable_badges_emotes": True,
                    "available_drops_check": True,
                },
            ) as response:
                self.assertEqual(response.status, 200)

        self.assertEqual(twitch.settings.priority, ["Game A"])
        self.assertEqual(twitch.settings.exclude, {"Game B"})
        self.assertEqual(twitch.state, State.RESTART)
        self.assertTrue(twitch.settings.enable_badges_emotes)
        self.assertTrue(twitch.settings.available_drops_check)
        self.assertTrue(twitch.settings.saved)
        gui.close()
        await gui._server_task


class EnglishOnlyTest(unittest.TestCase):
    def test_translator_exposes_only_english_in_container_mode(self):
        from translate import Translator

        with patch.dict(os.environ, {"TDM_ENGLISH_ONLY": "1"}):
            self.assertEqual(list(Translator().languages), ["English"])


if __name__ == "__main__":
    unittest.main()
