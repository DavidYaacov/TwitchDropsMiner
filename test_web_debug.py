import unittest
from types import SimpleNamespace

from aiohttp import web

from web_debug import WebDebug


class WebDebugTest(unittest.TestCase):
    def test_device_login_scenario(self):
        debug = WebDebug(lambda request: None)
        state = {"login": {}, "activity": []}

        debug.scenario = "device_login"
        result = debug.apply(state)
        self.assertEqual(result["login"]["user_code"], "ABCD-EFGH")
        self.assertFalse(result["login"]["connected"])


class WebDebugRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_custom_campaign_options_are_validated_and_applied(self):
        debug = WebDebug(lambda request: None)

        async def payload():
            return {
                "scenario": "custom_active",
                "campaign_count": 7,
                "progress_percent": 75,
                "channel_name": "layout_test_channel",
                "long_labels": True,
            }

        await debug.set_scenario(SimpleNamespace(json=payload))
        result = debug.apply({"login": {}, "activity": []})
        self.assertEqual(len(result["campaigns"]), 7)
        self.assertEqual(result["mining"][0]["channel"], "layout_test_channel")
        self.assertEqual(result["campaigns"][0]["progress"], 0.75)
        self.assertIn("Extra Long", result["campaigns"][0]["name"])

        async def invalid_payload():
            return {"scenario": "custom_active", "campaign_count": 21}

        with self.assertRaises(web.HTTPBadRequest):
            await debug.set_scenario(SimpleNamespace(json=invalid_payload))


if __name__ == "__main__":
    unittest.main()
