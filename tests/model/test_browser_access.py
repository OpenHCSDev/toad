"""Exercise the real vendor routes behind the browser authentication boundary."""
import asyncio
import socket
import stat

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from agent_comms.field_codec import FieldCodec, MalformedRecord

from toad.web_server import (
    LocalBrowserAuthentication,
    LocalBrowserEndpoint,
    OwnerOnlyDirectory,
    TailnetBrowserEndpoint,
    TailscaleStatus,
    ToadWebServer,
)


@pytest.fixture
def runtime(tmp_path) -> OwnerOnlyDirectory:
    return OwnerOnlyDirectory.decode(tmp_path / "runtime")


@pytest.fixture
def tailnet_status() -> TailscaleStatus:
    return FieldCodec.decode(TailscaleStatus, FieldCodec.parse('''{
        "Self": {"DNSName": "owner.example.ts.net.", "UserID": 42, "Online": true},
        "User": {"42": {"LoginName": "owner@example.test", "DisplayName": "Owner"}},
        "BackendState": "Running"
    }'''))


def test_status_owns_the_node_origin_and_owner(
    tailnet_status: TailscaleStatus, runtime: OwnerOnlyDirectory
) -> None:
    authentication = tailnet_status.authentication(8443, runtime)
    assert authentication.owner.LoginName == "owner@example.test"
    assert authentication.entry_url == "https://owner.example.ts.net:8443/"
    assert tailnet_status.authentication(443, runtime).endpoint.url == "https://owner.example.ts.net"


@pytest.mark.parametrize("wire", [
    '{"Self":{"DNSName":"host","UserID":"42"},"User":{}}',
    '{"Self":{"DNSName":"host","UserID":42},"User":{"42":{"LoginName":""}}}',
])
def test_malformed_status_is_refused_at_ingress(wire: str) -> None:
    with pytest.raises(MalformedRecord):
        FieldCodec.decode(TailscaleStatus, FieldCodec.parse(wire))


def test_tailnet_owner_and_untrusted_requests_use_the_real_routes(
    tailnet_status: TailscaleStatus, runtime: OwnerOnlyDirectory,
) -> None:
    async def journey() -> None:
        authentication = tailnet_status.authentication(8443, runtime)
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
                            page = await response.text()
                            assert f"wss://{endpoint.authority}/ws" in page
                            assert 'name="viewport"' in page
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


def test_tailnet_endpoint_listens_only_on_an_owner_only_socket(runtime: OwnerOnlyDirectory) -> None:
    endpoint = TailnetBrowserEndpoint("owner.example.ts.net", 8443, runtime)
    # A dead server's leftover path is reclaimed by the next lock holder.
    endpoint.socket_path.touch()
    with endpoint.listening() as listener:
        assert listener.family == socket.AF_UNIX
        assert stat.S_IMODE(endpoint.socket_path.stat().st_mode) == 0o600
    assert not endpoint.socket_path.exists()


def test_a_starting_server_keeps_its_socket(runtime: OwnerOnlyDirectory) -> None:
    endpoint = TailnetBrowserEndpoint("owner.example.ts.net", 8443, runtime)
    with endpoint.listening():
        # Bound but not yet listening: connects are refused, yet the server is alive.
        with pytest.raises(RuntimeError, match="holds"):
            with endpoint.listening():
                pass
        assert endpoint.socket_path.exists()


@pytest.mark.parametrize("mode", [0o750, 0o755, 0o777])
def test_runtime_directory_others_can_enter_is_refused(tmp_path, mode: int) -> None:
    directory = tmp_path / "runtime"
    directory.mkdir()
    directory.chmod(mode)
    with pytest.raises(RuntimeError, match="mode 0700"):
        OwnerOnlyDirectory.decode(directory)


def test_runtime_directory_symlink_is_refused(tmp_path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    (tmp_path / "link").symlink_to(target)
    with pytest.raises(RuntimeError, match="not a directory"):
        OwnerOnlyDirectory.decode(tmp_path / "link")
