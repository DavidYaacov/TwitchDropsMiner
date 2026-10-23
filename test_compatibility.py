import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import aiohttp

from channel import Channel, Stream
from constants import ClientType
from exceptions import ExitRequest, GQLException, LoginException, RequestException
from inventory import DropsCampaign
from settings import Settings, default_settings
from twitch import Twitch
from utils import Game


class Response:
    def __init__(self, data=None, status=200, text=""):
        self.data, self.status, self.body = data, status, text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self, **kwargs):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data

    async def text(self, *args, **kwargs):
        return self.body


def client():
    settings = SimpleNamespace(**deepcopy(default_settings), save=Mock(), dump=False)
    with patch("twitch.WebGUIManager"):
        twitch = Twitch(settings)
    twitch.gui.login.ask_enter_code = AsyncMock()
    twitch.gui.inv.add_campaign = AsyncMock()
    twitch.gui.close_requested = False
    twitch._auth_state.device_id = "device"
    twitch._auth_state._device_id_host = twitch._client_type.CLIENT_URL.host
    return twitch


def campaign_data(cid="campaign"):
    return {
        "id": cid,
        "name": "Campaign",
        "game": {"id": "123", "name": "Game"},
        "startAt": "2026-01-01T00:00:00Z",
        "endAt": "2099-01-01T00:00:00Z",
        "timeBasedDrops": [
            {
                "id": "drop",
                "requiredMinutesWatched": 30,
                "benefitEdges": [{"benefit": {"id": "reward"}}],
            }
        ],
    }


def channel(twitch, channel_id=1):
    result = Channel(twitch, id=channel_id, login=f"channel{channel_id}")
    result._stream = Stream(
        result, id=channel_id, game={"id": "123", "name": "Game"}, viewers=10, title="Live"
    )
    return result


def stream_data(channel_id=1):
    return {
        "id": str(channel_id),
        "displayName": "Channel",
        "stream": {"id": "1", "viewersCount": 3},
        "broadcastSettings": {"game": {"id": "124", "name": "Other"}, "title": "new"},
    }


class SettingsCompatibilityTests(unittest.TestCase):
    def test_old_settings_gain_defaults_and_selection_survives_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "settings.json")
            path.write_text(json.dumps({"available_drops_check": False}), encoding="utf8")
            with patch("settings.SETTINGS_PATH", path):
                settings = Settings(SimpleNamespace())
                self.assertFalse(settings.available_drops_check)
                self.assertTrue(settings.campaign_discovery)
                self.assertEqual(settings.client_type, "SMARTBOX")
                settings.client_type = "MOBILE_WEB"
                settings.save()
                self.assertEqual(Settings(SimpleNamespace()).client_type, "MOBILE_WEB")


class AuthenticationCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_saved_client_uses_default(self):
        settings = SimpleNamespace(client_type="RETIRED")
        with patch("twitch.WebGUIManager"):
            twitch = Twitch(settings)
        self.assertIs(twitch._client_type, ClientType.SMARTBOX)
        self.assertEqual(settings.client_type, "SMARTBOX")

    async def test_rejected_client_falls_back_and_saves_matching_headers(self):
        twitch = client()
        twitch.settings.client_type = twitch.client_type_name = "ANDROID_APP"
        twitch._client_type = ClientType.ANDROID_APP
        twitch._session = SimpleNamespace(headers={})
        accepted = {
            "device_code": "code",
            "user_code": "ABCD",
            "interval": 5,
            "expires_in": 1800,
            "verification_uri": "https://www.twitch.tv/activate",
        }
        twitch.request = Mock(
            side_effect=[
                Response({"message": "invalid client"}, 400),
                Response(accepted),
            ]
        )
        self.assertEqual(await twitch._auth_state._request_device_code(), accepted)
        self.assertIs(twitch._client_type, ClientType.SMARTBOX)
        self.assertEqual(twitch.settings.client_type, "SMARTBOX")
        twitch.settings.save.assert_called_once()
        self.assertEqual(twitch._session.headers["User-Agent"], ClientType.SMARTBOX.USER_AGENT)
        second = twitch.request.call_args_list[1].kwargs
        self.assertEqual(second["data"]["client_id"], second["headers"]["Client-Id"])

    async def test_malformed_device_responses_fail_without_keyerror(self):
        twitch = client()
        twitch.request = Mock(
            side_effect=[
                Response(json.JSONDecodeError("invalid", "", 0)),
                Response([]),
                Response({"device_code": "incomplete"}),
                Response({"message": "invalid client"}, 400),
            ]
        )
        with self.assertRaisesRegex(LoginException, "every known client"):
            await twitch._auth_state._request_device_code()
        self.assertEqual(twitch.request.call_count, 4)

    async def test_saved_token_adopts_issuing_client_without_new_login(self):
        twitch = client()
        auth = twitch._auth_state
        jar = aiohttp.CookieJar()
        jar.update_cookies({"auth-token": "saved"}, ClientType.ANDROID_APP.CLIENT_URL)
        twitch.get_session = AsyncMock(return_value=SimpleNamespace(cookie_jar=jar))
        twitch.request = Mock(
            return_value=Response(
                {
                    "client_id": ClientType.ANDROID_APP.CLIENT_ID,
                    "user_id": "42",
                }
            )
        )
        auth._fetch_device_id = AsyncMock()
        auth._oauth_login = AsyncMock()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("twitch.COOKIES_PATH", Path(folder, "cookies.jar")),
        ):
            await auth.validate()
            self.assertTrue(Path(folder, "cookies.jar").exists())
        self.assertEqual(auth.user_id, 42)
        self.assertEqual(auth.access_token, "saved")
        self.assertTrue(auth._logged_in.is_set())
        self.assertIs(twitch._client_type, ClientType.ANDROID_APP)
        auth._oauth_login.assert_not_awaited()
        auth._fetch_device_id.assert_awaited_once_with(jar)

    async def test_device_polling_uses_selected_client_and_refreshed_device_id(self):
        twitch = client()
        auth = twitch._auth_state
        twitch.get_session = AsyncMock(return_value=SimpleNamespace(cookie_jar=aiohttp.CookieJar()))

        async def code():
            twitch.set_client_type("MOBILE_WEB")
            return {
                "device_code": "code",
                "user_code": "ABCD",
                "interval": 5,
                "expires_in": 1800,
                "verification_uri": "https://www.twitch.tv/activate",
            }

        async def fetch_device(jar):
            auth.device_id = "mobile-device"
            auth._device_id_host = "m.twitch.tv"

        auth._request_device_code = AsyncMock(side_effect=code)
        auth._fetch_device_id = AsyncMock(side_effect=fetch_device)
        twitch.request = Mock(side_effect=[Response({}, 400), Response({"access_token": "fresh"})])
        with patch("twitch.asyncio.sleep", new=AsyncMock()):
            self.assertEqual(await auth._oauth_login(), "fresh")
        for call in twitch.request.call_args_list:
            self.assertEqual(call.kwargs["headers"]["Client-Id"], ClientType.MOBILE_WEB.CLIENT_ID)
            self.assertEqual(call.kwargs["data"]["client_id"], ClientType.MOBILE_WEB.CLIENT_ID)
            self.assertEqual(call.kwargs["headers"]["X-Device-Id"], "mobile-device")
        auth._fetch_device_id.assert_awaited_once()

    async def test_expired_cookie_reauthenticates(self):
        twitch = client()
        jar = aiohttp.CookieJar()
        jar.update_cookies({"auth-token": "expired"}, twitch._client_type.CLIENT_URL)
        twitch.get_session = AsyncMock(return_value=SimpleNamespace(cookie_jar=jar))
        auth = twitch._auth_state
        auth._oauth_login = AsyncMock(return_value="fresh")
        twitch.request = Mock(
            side_effect=[
                Response({}, 401),
                Response(
                    {
                        "client_id": ClientType.SMARTBOX.CLIENT_ID,
                        "user_id": "42",
                    }
                ),
            ]
        )
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("twitch.COOKIES_PATH", Path(folder, "cookies.jar")),
        ):
            await auth.validate()
        self.assertEqual(auth.access_token, "fresh")
        auth._oauth_login.assert_awaited_once()

    async def test_validation_server_errors_leave_cookie_intact(self):
        twitch = client()
        jar = aiohttp.CookieJar()
        jar.update_cookies({"auth-token": "saved"}, twitch._client_type.CLIENT_URL)
        twitch.get_session = AsyncMock(return_value=SimpleNamespace(cookie_jar=jar))
        twitch.request = Mock(return_value=Response({}, 503))
        with self.assertRaisesRegex(RuntimeError, "unexpected validation response"):
            await twitch._auth_state.validate()
        self.assertEqual(
            jar.filter_cookies(twitch._client_type.CLIENT_URL)["auth-token"].value, "saved"
        )


class DiscoveryCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_fields_and_removed_or_cyclic_prerequisites(self):
        twitch = client()
        data = campaign_data()
        data["timeBasedDrops"] += [
            {"id": "sub", "requiredMinutesWatched": 10, "requiredSubs": 1},
            {"id": "dependent", "requiredMinutesWatched": 10, "preconditionDrops": [{"id": "sub"}]},
            {"id": "cycle", "requiredMinutesWatched": 10, "preconditionDrops": [{"id": "cycle"}]},
            {"id": "bad-date", "requiredMinutesWatched": 10, "endAt": "bad"},
            {"id": "no-time", "requiredMinutesWatched": 0},
        ]
        skipped = {}
        converted = twitch._campaign_from_available(data, {}, skipped)
        parsed = DropsCampaign(twitch, converted, {})
        self.assertEqual(list(parsed.timed_drops), ["drop"])
        self.assertEqual(parsed.first_drop.name, "Campaign")
        self.assertEqual(parsed.first_drop.required_minutes, 30)
        self.assertEqual(skipped["unusable drop"], 3)

    async def test_no_game_or_no_expiry_does_not_invent_campaign(self):
        twitch = client()
        data = campaign_data()
        data["game"] = None
        skipped = {}
        self.assertIsNone(twitch._campaign_from_available(data, {}, skipped))
        self.assertEqual(skipped["no game"], 1)
        data = campaign_data()
        del data["endAt"]
        self.assertIsNone(twitch._campaign_from_available(data, {}, {}))

    async def test_failed_batch_retains_other_answers(self):
        twitch = client()
        twitch.gql_request = AsyncMock(
            side_effect=[
                [{"data": {"channel": {"id": "1", "viewerDropCampaigns": []}}}],
                GQLException("integrity error"),
                [{"data": {"channel": {"id": "41", "viewerDropCampaigns": [{"id": "c"}]}}}],
            ]
        )
        self.assertEqual(
            await twitch.fetch_available_drops(range(1, 42)), {1: [], 41: [{"id": "c"}]}
        )
        self.assertEqual(twitch.gql_request.await_count, 3)

    async def test_discovery_preserves_known_data_filters_exclusions_and_reports(self):
        twitch = client()
        twitch.settings.priority = ["Game", "Excluded"]
        twitch.settings.exclude = {"Excluded"}
        known = {
            "known": {"game": {"id": "123", "name": "Game"}, "self": {"isAccountConnected": False}}
        }
        twitch.get_live_streams = AsyncMock(return_value=[channel(twitch, 1), channel(twitch, 2)])
        twitch.fetch_available_drops = AsyncMock(
            return_value={
                1: [campaign_data(), campaign_data("known"), {"id": "malformed"}, None],
                2: [campaign_data()],
            }
        )
        result = await twitch.discover_campaigns(known)
        self.assertEqual(list(result), ["campaign"])
        self.assertFalse(result["campaign"]["self"]["isAccountConnected"])
        self.assertEqual(len(result["campaign"]["allow"]["channels"]), 2)
        self.assertEqual(twitch.get_live_streams.await_count, 1)
        self.assertIn("known", known)
        self.assertIn("Drops scan:", twitch.gui.print.call_args.args[0])

    async def test_discovery_does_not_swallow_shutdown(self):
        twitch = client()
        twitch.settings.priority = ["Game"]
        twitch.get_live_streams = AsyncMock(side_effect=ExitRequest())
        with self.assertRaises(ExitRequest):
            await twitch.discover_campaigns({})

    async def test_failed_dashboard_keeps_progress_and_adds_discovered_campaign(self):
        twitch = client()
        known = twitch._campaign_from_available(campaign_data("known"), {}, {})
        known["timeBasedDrops"][0]["self"] = {
            "currentMinutesWatched": 7,
            "isClaimed": False,
            "dropInstanceID": None,
        }
        twitch.gql_request = AsyncMock(
            side_effect=[
                {
                    "data": {
                        "currentUser": {
                            "inventory": {
                                "dropCampaignsInProgress": [known],
                                "gameEventDrops": [],
                            }
                        }
                    }
                },
                GQLException("integrity error"),
            ]
        )
        discovered = twitch._campaign_from_available(campaign_data("new"), {}, {})
        discovered["timeBasedDrops"][0]["id"] = "new-drop"
        twitch.discover_campaigns = AsyncMock(return_value={"new": discovered})
        twitch._campaigns["stale"] = object()
        with patch.object(twitch, "_maintenance_task", new=AsyncMock()):
            await twitch.fetch_inventory()
            await twitch._mnt_task
        self.assertEqual(set(twitch._campaigns), {"known", "new"})
        self.assertEqual(twitch._campaigns["known"].timed_drops["drop"].real_current_minutes, 7)

    async def test_refused_details_and_null_directory_are_tolerated(self):
        twitch = client()
        twitch.get_auth = AsyncMock(return_value=SimpleNamespace(user_id=42))
        twitch.gql_request = AsyncMock(side_effect=GQLException("integrity error"))
        self.assertEqual(await twitch.fetch_campaigns([("c", {})]), {})
        twitch.gql_request = AsyncMock(return_value={"data": {"game": None}})
        self.assertEqual(await twitch.get_live_streams(Game({"id": 123, "name": "Game"})), [])


class ChannelCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_directory_check_distinguishes_empty_and_unanswered(self):
        twitch = client()
        twitch.settings.available_drops_check = False
        channels = [channel(twitch, n) for n in (1, 2, 3)]
        twitch._campaigns = {"c": SimpleNamespace(can_earn=lambda *args, **kwargs: True)}
        twitch.fetch_available_drops = AsyncMock(return_value={1: [], 2: [{"id": "c"}]})
        await twitch.check_available_drops(channels)
        self.assertEqual([c.drops_enabled for c in channels], [False, True, True])
        self.assertEqual(channels[0].url, "https://www.twitch.tv/channel1")

    async def test_all_empty_or_failed_retains_eligibility(self):
        twitch = client()
        live = channel(twitch)
        for result in ({}, {1: []}):
            twitch.fetch_available_drops = AsyncMock(return_value=result)
            await twitch.check_available_drops([live])
            self.assertTrue(live.drops_enabled)

    async def test_both_checks_can_be_disabled_explicitly(self):
        twitch = client()
        twitch.settings.campaign_discovery = False
        twitch.settings.available_drops_check = False
        twitch.fetch_available_drops = AsyncMock()
        await twitch.check_available_drops([channel(twitch)])
        twitch.fetch_available_drops.assert_not_awaited()

    async def test_bulk_update_handles_generators_and_offline_channels(self):
        twitch = client()
        channels = [channel(twitch, 1), channel(twitch, 2)]
        twitch.gql_request = AsyncMock(
            return_value=[
                {"data": {"user": {"id": "1", "stream": None}}},
                {"data": {"user": stream_data(2)}},
            ]
        )
        twitch.fetch_available_drops = AsyncMock(return_value={2: [{"id": "c"}]})
        twitch._campaigns = {"c": SimpleNamespace(can_earn=lambda *args, **kwargs: True)}
        await twitch.bulk_check_online(iter(channels))
        self.assertFalse(channels[0].online)
        self.assertTrue(channels[1].drops_enabled)

    async def test_stream_update_rechecks_explicit_negative(self):
        twitch = client()
        live = channel(twitch)
        twitch.gql_request = AsyncMock(return_value={"data": {"user": stream_data()}})
        twitch.fetch_available_drops = AsyncMock(return_value={1: []})
        stream = await live.get_stream()
        self.assertFalse(stream.drops_enabled)
        self.assertEqual(stream.game.id, 124)

    async def test_watch_uses_playlist_and_checks_every_chunk(self):
        twitch = client()
        live = channel(twitch)
        live._stream.get_stream_url = AsyncMock(return_value="https://cdn.example/live.m3u8")
        twitch.request = Mock(
            side_effect=[
                Response(
                    text="#EXTM3U\nhttps://cdn.example/1.ts\nhttps://cdn.example/2.ts\n"
                    "#EXT-X-ENDLIST"
                ),
                Response(),
                Response(),
            ]
        )
        self.assertTrue(await live.send_watch())
        self.assertEqual(
            [call.args[0] for call in twitch.request.call_args_list], ["GET", "HEAD", "HEAD"]
        )

    async def test_watch_empty_error_and_failed_chunk_are_not_success(self):
        twitch = client()
        live = channel(twitch)
        live._stream.get_stream_url = AsyncMock(return_value="https://cdn.example/live.m3u8")
        for body in ("", "#EXTM3U\n#EXT-X-ENDLIST", "[]", '{"error":"offline"}'):
            twitch.request = Mock(return_value=Response(text=body))
            self.assertFalse(await live.send_watch())
        twitch.request = Mock(
            side_effect=[
                Response(text="https://cdn.example/1.ts"),
                Response(status=404),
            ]
        )
        self.assertFalse(await live.send_watch())
        live._stream.get_stream_url = AsyncMock(side_effect=RequestException())
        self.assertFalse(await live.send_watch())


if __name__ == "__main__":
    unittest.main()
