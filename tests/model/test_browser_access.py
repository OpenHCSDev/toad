"""Exercise the real vendor routes behind the browser authentication boundary."""
import asyncio

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from agent_comms.field_codec import FieldCodec, MalformedRecord

from toad.web_server import (
    BrowserAuthentication,
    LocalBrowserAuthentication,
    LocalBrowserEndpoint,
    TailscaleStatus,
    ToadWebServer,
)


@pytest.fixture
def tailnet_status() -> TailscaleStatus:
    return FieldCodec.decode(TailscaleStatus, FieldCodec.parse('''{
        "Self": {"DNSName": "owner.example.ts.net.", "UserID": 42, "Online": true},
        "User": {"42": {"LoginName": "owner@example.test", "DisplayName": "Owner"}},
        "BackendState": "Running"
    }'''))


def test_status_owns_the_node_origin_and_owner(tailnet_status: TailscaleStatus) -> None:
    authentication = tailnet_status.authentication("127.0.0.1", 8000, 8443)
    assert authentication.owner.LoginName == "owner@example.test"
    assert authentication.entry_url == "https://owner.example.ts.net:8443/"
    assert tailnet_status.Self.origin(443) == "https://owner.example.ts.net"
    assert isinstance(
        BrowserAuthentication.from_option("127.0.0.1", 8000, None),
        LocalBrowserAuthentication,
    )


@pytest.mark.parametrize("wire", [
    '{"Self":{"DNSName":"host","UserID":"42"},"User":{}}',
    '{"Self":{"DNSName":"host","UserID":42},"User":{"42":{"LoginName":""}}}',
])
def test_malformed_status_is_refused_at_ingress(wire: str) -> None:
    with pytest.raises(MalformedRecord):
        FieldCodec.decode(TailscaleStatus, FieldCodec.parse(wire))


def test_tailnet_owner_and_untrusted_requests_use_the_real_routes(
    tailnet_status: TailscaleStatus,
) -> None:
    async def journey() -> None:
        authentication = tailnet_status.authentication("127.0.0.1", 8000, 8443)
        endpoint = authentication.endpoint
        server = ToadWebServer("unused: HTTP requests must not start a child", authentication)
        async with TestServer(await server._make_app()) as listening:
            async with aiohttp.ClientSession() as client:
                cases = (
                    ("/", [("Host", endpoint.authority), ("Tailscale-User-Login", "owner@example.test")], 200),
                    ("/", [("Host", endpoint.authority), ("Tailscale-User-Login", "other@example.test")], 403),
                    ("/", [("Host", endpoint.authority)], 403),
                    ("/", [("Host", endpoint.authority), ("Tailscale-User-Login", "owner@example.test"), ("Tailscale-User-Login", "owner@example.test")], 403),
                    ("/", [("Host", "foreign.example"), ("Tailscale-User-Login", "owner@example.test")], 403),
                    ("/ws", [("Host", endpoint.authority), ("Tailscale-User-Login", "owner@example.test")], 403),
                    ("/ws", [("Host", endpoint.authority), ("Origin", "https://foreign.example"), ("Tailscale-User-Login", "owner@example.test")], 403),
                    ("/download/missing", [("Host", endpoint.authority), ("Tailscale-User-Login", "other@example.test")], 403),
                    ("/static/js/textual.js", [("Host", endpoint.authority), ("Tailscale-User-Login", "other@example.test")], 403),
                )
                for path, headers, expected in cases:
                    async with client.get(listening.make_url(path), headers=headers) as response:
                        assert response.status == expected, (path, headers)
                        assert response.headers["Cache-Control"] == "no-store"
                        assert response.headers["X-Frame-Options"] == "DENY"
                        if expected == 200:
                            assert f"wss://{endpoint.authority}/ws" in await response.text()
    asyncio.run(journey())


def test_local_bootstrap_still_requires_its_capability() -> None:
    async def journey() -> None:
        endpoint = LocalBrowserEndpoint("127.0.0.1", 8000)
        authentication = LocalBrowserAuthentication(endpoint)
        server = ToadWebServer("unused: HTTP requests must not start a child", authentication)
        async with TestServer(await server._make_app()) as listening:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as client:
                headers = {"Host": endpoint.authority}
                async with client.get(listening.make_url("/"), headers=headers) as response:
                    assert response.status == 403
                async with client.get(
                    listening.make_url("/").with_query(token=authentication.capability),
                    headers=headers, allow_redirects=False,
                ) as response:
                    assert response.status == 303
                    assert response.cookies[endpoint.cookie_name]["httponly"]
                    assert response.cookies[endpoint.cookie_name]["samesite"] == "Strict"
                async with client.get(listening.make_url("/"), headers=headers) as response:
                    assert response.status == 200
    asyncio.run(journey())
