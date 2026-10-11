"""Usage reports build their TLS context once, not for every report."""

from types import SimpleNamespace
import unittest
from unittest import mock

import httpx

from toad.application_lifetime import UsageReports


class UsageTls(unittest.IsolatedAsyncioTestCase):
    async def test_the_tls_context_is_built_once(self):
        async def run_thread(function, *args):
            return function(*args)

        app = SimpleNamespace(
            preparation=SimpleNamespace(run_thread=run_thread), size=(80, 24),
            settings=SimpleNamespace(anon_id="anon"), terminal_attention=SimpleNamespace(program="st"),
        )
        reports = UsageReports(app)
        clients = []

        class Client:
            def __init__(self, *, verify):
                clients.append(verify)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json):
                return None

        import toad

        with mock.patch.object(httpx, "create_ssl_context", side_effect=lambda: object()) as create, \
                mock.patch.object(httpx, "AsyncClient", Client), \
                mock.patch.object(toad, "get_version", return_value="test"):
            await reports.deliver("first", {})
            await reports.deliver("second", {})
        self.assertEqual(create.call_count, 1)
        self.assertEqual(len(clients), 2)
        self.assertIs(clients[0], clients[1])


if __name__ == "__main__":
    unittest.main()
