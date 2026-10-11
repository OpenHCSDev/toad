"""Usage reports build their TLS context once, not for every report."""

from types import SimpleNamespace
from unittest import mock

import httpx

import toad
from toad.application_lifetime import UsageReports


async def test_the_tls_context_is_built_once():
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

    with mock.patch.object(httpx, "create_ssl_context", side_effect=lambda: object()) as create, \
            mock.patch.object(httpx, "AsyncClient", Client), \
            mock.patch.object(toad, "get_version", return_value="test"):
        await reports.deliver("first", {})
        await reports.deliver("second", {})
    assert create.call_count == 1
    assert len(clients) == 2
    assert clients[0] is clients[1]
