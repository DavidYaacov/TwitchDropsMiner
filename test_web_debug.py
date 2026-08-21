import unittest

from web_debug import WebDebug


class WebDebugTest(unittest.TestCase):
    def test_multi_active_scenario_has_three_mining_campaigns(self):
        debug = WebDebug(lambda request: None)
        debug.scenario = "multi_active"
        state = {"login": {}, "activity": []}

        result = debug.apply(state)

        self.assertEqual(len(result["mining"]), 3)
        self.assertEqual(len(result["campaigns"]), 3)
        self.assertEqual({item["channel"] for item in result["mining"]}, {"debug_channel"})
        self.assertEqual(result["debug"]["scenario"], "multi_active")


if __name__ == "__main__":
    unittest.main()
