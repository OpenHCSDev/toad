"""Local-only authentication boundary for the existing textual-serve routes.

Textual-serve starts a new Toad subprocess on each accepted WebSocket. Keep the
boundary at the aiohttp application, before *any* route handler is dispatched.
"""

from __future__ import annotations

import logging
import secrets
from importlib.metadata import version
from urllib.parse import quote

from aiohttp import web
from textual_serve.server import Server


class ToadWebServer(Server):
    """Serve Toad only to a local browser holding this process's capability."""

    def __init__(
        self,
        command: str,
        *,
        host: str = "localhost",
        port: int = 8000,
        title: str | None = None,
        public_url: str | None = None,
    ) -> None:
        if version("textual-serve") != "1.1.3":
            raise RuntimeError("Browser serving requires reviewed textual-serve 1.1.3")
        if host not in {"localhost", "127.0.0.1"} or not 1 <= port <= 65535:
            raise ValueError(
                "Browser serving requires a loopback host and a valid port"
            )
        expected_url = f"http://{host}:{port}"
        if public_url is not None and public_url != expected_url:
            raise ValueError("Browser serving cannot use a non-local public URL")
        super().__init__(
            command, host=host, port=port, title=title, public_url=expected_url
        )
        self._capability = secrets.token_urlsafe(32)
        # Browser cookies are scoped to hosts, not ports. Separate concurrent
        # local Toad servers must not replace each other's session cookie.
        self._cookie_name = f"toad_web_session_{port}"
        self._expected_host = f"{host}:{port}"

    def initialize_logging(self) -> None:
        super().initialize_logging()
        # The bootstrap URL contains a per-process bearer secret. Never log URLs.
        logging.getLogger("aiohttp.access").disabled = True

    async def on_startup(self, app: web.Application) -> None:
        self.console.print("Toad local browser (keep this URL private):")
        self.console.print(f"{self.public_url}/?token={quote(self._capability)}")

    @staticmethod
    def _secure_headers(response: web.StreamResponse) -> web.StreamResponse:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    async def _make_app(self) -> web.Application:
        app = await super()._make_app()
        capability = self._capability
        expected_host = self._expected_host
        expected_origin = self.public_url
        cookie_name = self._cookie_name

        @web.middleware
        async def local_capability(request: web.Request, handler):
            # Check the literal Host, not DNS resolution: prevents DNS rebinding.
            hosts = request.headers.getall("Host", [])
            origins = request.headers.getall("Origin", [])
            websocket = request.path == "/ws"
            if (
                len(hosts) != 1
                or hosts[0] != expected_host
                or (websocket and origins != [expected_origin])
                or (origins and origins != [expected_origin])
            ):
                return self._secure_headers(web.Response(status=403))

            # The only query-token exchange is an index navigation. Redirect
            # immediately: the secret does not enter HTML, static/WS URLs, or
            # the browser's retained location. The subsequent routes need a
            # same-site, HttpOnly cookie, including downloads and static files.
            if request.path == "/" and "token" in request.query:
                token = request.query.get("token", "")
                if request.method != "GET" or not secrets.compare_digest(
                    token, capability
                ):
                    return self._secure_headers(web.Response(status=403))
                response = web.Response(status=303, headers={"Location": "/"})
                response.set_cookie(
                    cookie_name, capability, httponly=True, samesite="Strict", path="/"
                )
                return self._secure_headers(response)

            if not secrets.compare_digest(
                request.cookies.get(cookie_name, ""), capability
            ):
                return self._secure_headers(web.Response(status=403))
            # Streaming handlers prepare their own response; the prepare hook
            # supplies headers before they can send their first byte.
            return self._secure_headers(await handler(request))

        # All four textual-serve routes (index, static, WS, download) pass
        # through this middleware before WS prepare / AppService.start. Add
        # headers on prepare too: download/WS may prepare before returning.
        async def on_response_prepare(
            request: web.Request, response: web.StreamResponse
        ) -> None:
            self._secure_headers(response)

        app.middlewares.append(local_capability)
        app.on_response_prepare.append(on_response_prepare)
        return app
