"""Provider-free security checks for the local Textual browser gate."""

import socket
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, CookieJar, WSServerHandshakeError
from aiohttp.test_utils import TestServer
from textual_serve.app_service import AppService

from toad.web_server import ToadWebServer


def unused_loopback_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class BrowserGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.port = unused_loopback_port()
        self.origin = f"http://127.0.0.1:{self.port}"
        self.server = ToadWebServer("false", host="127.0.0.1", port=self.port)
        self.site = TestServer(
            await self.server._make_app(), host="127.0.0.1", port=self.port
        )
        with patch.object(self.server.console, "print"):
            await self.site.start_server()
        self.client = ClientSession(cookie_jar=CookieJar(unsafe=True))
        self.base = str(self.site.make_url("/")).rstrip("/")

    async def asyncTearDown(self):
        await self.client.close()
        await self.site.close()

    async def request(self, path, *, headers=None, client=None, redirects=True):
        async with (client or self.client).get(
            self.base + path, headers=headers, allow_redirects=redirects
        ) as response:
            await response.read()
            return response.status, dict(response.headers)

    async def ws_status(self, *, headers=None, client=None):
        try:
            async with (client or self.client).ws_connect(
                self.base + "/ws", headers=headers
            ) as ws:
                return ws._response.status
        except WSServerHandshakeError as error:
            return error.status

    async def authenticate(self):
        status, headers = await self.request(
            f"/?token={self.server._capability}", redirects=False
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertNotIn("token", headers["Location"])
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["Content-Security-Policy"], "frame-ancestors 'none'")

    async def test_authentication_precedes_all_handlers_and_child_spawn(self):
        with patch.object(AppService, "start", new_callable=AsyncMock) as spawn:
            for path in ("/", "/static/css/xterm.css", "/download/missing"):
                status, headers = await self.request(path)
                self.assertEqual(status, 403, path)
                self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(await self.ws_status(headers={"Origin": self.origin}), 403)
            self.assertEqual(
                await self.ws_status(headers={"Origin": "https://malicious.example"}),
                403,
            )
            self.assertEqual(
                (await self.request("/?token=wrong", redirects=False))[0], 403
            )
            self.assertEqual(
                (
                    await self.request(
                        f"/?token={self.server._capability}",
                        headers={"Host": "attacker.example"},
                        redirects=False,
                    )
                )[0],
                403,
            )
            await self.authenticate()
            for bad_origin in (
                {},
                {"Origin": "null"},
                {"Origin": "https://malicious.example"},
            ):
                self.assertEqual(await self.ws_status(headers=bad_origin), 403)
            self.assertEqual(
                await self.ws_status(
                    headers={"Host": "attacker.example", "Origin": self.origin}
                ),
                403,
            )
            self.assertEqual(
                (
                    await self.request(
                        "/static/css/xterm.css", headers={"Host": "attacker.example"}
                    )
                )[0],
                403,
            )
            self.assertEqual(
                (
                    await self.request(
                        "/download/missing", headers={"Host": "attacker.example"}
                    )
                )[0],
                403,
            )
            self.assertEqual(
                (await self.request("/", headers={"Origin": "null"}))[0], 403
            )
            spawn.assert_not_awaited()

            self.assertEqual((await self.request("/"))[0], 200)
            status, headers = await self.request("/static/css/xterm.css")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
            self.assertEqual((await self.request("/download/missing"))[0], 404)

            class FakeService:
                calls = 0

                async def send_meta(fake, data):
                    fake.calls += 1
                    await self.server.download_manager.chunk_received(
                        "fixture", b"fake file\n" if fake.calls == 1 else b""
                    )
                    return True

            fake = FakeService()
            await self.server.download_manager.create_download(
                app_service=fake,
                delivery_key="fixture",
                file_name="fixture.txt",
                open_method="download",
                mime_type="text/plain",
            )
            async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as stranger:
                self.assertEqual(
                    (await self.request("/download/fixture", client=stranger))[0], 403
                )
            self.assertEqual(fake.calls, 0)
            async with self.client.get(self.base + "/download/fixture") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.read(), b"fake file\n")
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                self.assertEqual(
                    response.headers["Content-Security-Policy"],
                    "frame-ancestors 'none'",
                )
            self.assertEqual(await self.ws_status(headers={"Origin": self.origin}), 101)
            spawn.assert_awaited_once()

    def test_refuse_external_bind_and_public_url(self):
        with (
            patch("toad.web_server.version", return_value="1.1.4"),
            self.assertRaises(RuntimeError),
        ):
            ToadWebServer("false")
        for host in ("0.0.0.0", "::1", "localhost.attacker.example"):
            with self.assertRaises(ValueError):
                ToadWebServer("false", host=host, port=8000)
        with self.assertRaises(ValueError):
            ToadWebServer(
                "false",
                host="127.0.0.1",
                port=8000,
                public_url="https://malicious.example",
            )


if __name__ == "__main__":
    unittest.main()
