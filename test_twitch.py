import unittest
from types import SimpleNamespace
from unittest.mock import patch

from twitch import Twitch


class GqlRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_cancelled_is_retried(self):
        responses = iter(
            [
                {"errors": [{"message": "request cancelled"}]},
                {"data": {"ok": True}},
            ]
        )

        class Response:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def json(self):
                return next(responses)

        class Limiter:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

        client = Twitch.__new__(Twitch)
        client._qgl_limiter = Limiter()
        client._client_type = SimpleNamespace(USER_AGENT="test")

        async def get_auth():
            return SimpleNamespace(headers=lambda **kwargs: {})

        client.get_auth = get_auth
        client.request = lambda *args, **kwargs: Response()

        with patch("twitch.ExponentialBackoff", return_value=iter([0, 0])):
            result = await client.gql_request({"operationName": "test"})

        self.assertEqual(result, {"data": {"ok": True}})


if __name__ == "__main__":
    unittest.main()
