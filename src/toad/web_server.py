"""Authenticated loopback admission for the installed textual-serve routes."""

from __future__ import annotations

import logging
import secrets
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from importlib.metadata import version
from urllib.parse import quote

from aiohttp import web
from textual_serve.server import Server

type Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@dataclass(frozen=True)
class LocalBrowserEndpoint:
    host: str
    port: int

    def __post_init__(self) -> None:
        if self.host not in {"localhost", "127.0.0.1"} or not 1 <= self.port <= 65535:
            raise ValueError(
                "Browser serving requires a loopback host and a valid port"
            )

    @property
    def authority(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def url(self) -> str:
        return f"http://{self.authority}"

    @property
    def cookie_name(self) -> str:
        # Cookies have no port scope; concurrent local servers need distinct names.
        return f"toad_web_session_{self.port}"


class BrowserAdmission(ABC):
    async def dispatch(
        self, request: web.Request, handler: Handler
    ) -> web.StreamResponse:
        return self.secure(await self.respond(request, handler))

    @abstractmethod
    async def respond(
        self, request: web.Request, handler: Handler
    ) -> web.StreamResponse: ...

    @staticmethod
    def secure(response: web.StreamResponse) -> web.StreamResponse:
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "frame-ancestors 'none'",
                "X-Frame-Options": "DENY",
            }
        )
        return response


class RejectedBrowserAdmission(BrowserAdmission):
    async def respond(
        self, request: web.Request, handler: Handler
    ) -> web.StreamResponse:
        return web.Response(status=403)


class AuthenticatedBrowserAdmission(BrowserAdmission):
    async def respond(
        self, request: web.Request, handler: Handler
    ) -> web.StreamResponse:
        return await handler(request)


@dataclass(frozen=True)
class BootstrapBrowserAdmission(BrowserAdmission):
    authentication: LocalBrowserAuthentication

    async def respond(
        self, request: web.Request, handler: Handler
    ) -> web.StreamResponse:
        response = web.Response(status=303, headers={"Location": "/"})
        response.set_cookie(
            self.authentication.endpoint.cookie_name,
            self.authentication.capability,
            httponly=True,
            samesite="Strict",
            path="/",
        )
        return response


@dataclass(frozen=True)
class LocalBrowserAuthentication:
    endpoint: LocalBrowserEndpoint
    capability: str = field(
        default_factory=lambda: secrets.token_urlsafe(32), repr=False
    )

    @property
    def bootstrap_url(self) -> str:
        return f"{self.endpoint.url}/?token={quote(self.capability)}"

    def accepts(self, candidate: str) -> bool:
        # Compare bytes so an external non-ASCII credential is rejected, not a 500.
        return secrets.compare_digest(
            candidate.encode("utf-8", errors="surrogatepass"),
            self.capability.encode("ascii"),
        )

    def decode(self, request: web.Request) -> BrowserAdmission:
        """Decode external Host, Origin and credentials before any route handler."""
        hosts = request.headers.getall("Host", [])
        origins = request.headers.getall("Origin", [])
        if hosts != [self.endpoint.authority]:
            return RejectedBrowserAdmission()
        if request.path == "/ws" and origins != [self.endpoint.url]:
            return RejectedBrowserAdmission()
        if origins and origins != [self.endpoint.url]:
            return RejectedBrowserAdmission()
        token = request.query.get("token")
        if request.path == "/" and token is not None:
            if request.method == "GET" and self.accepts(token):
                return BootstrapBrowserAdmission(self)
            return RejectedBrowserAdmission()
        if self.accepts(request.cookies.get(self.endpoint.cookie_name, "")):
            return AuthenticatedBrowserAdmission()
        return RejectedBrowserAdmission()


class ToadWebServer(Server):
    """Keep the vendor server/child path; put local admission before every route."""

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
        endpoint = LocalBrowserEndpoint(host, port)
        if public_url is not None and public_url != endpoint.url:
            raise ValueError("Browser serving cannot use a non-local public URL")
        super().__init__(
            command, host=host, port=port, title=title, public_url=endpoint.url
        )
        self.authentication = LocalBrowserAuthentication(endpoint)

    def initialize_logging(self) -> None:
        super().initialize_logging()
        # Access URLs must never record the bootstrap bearer credential.
        logging.getLogger("aiohttp.access").disabled = True

    async def on_startup(self, app: web.Application) -> None:
        self.console.print("Toad local browser (keep this URL private):")
        self.console.print(self.authentication.bootstrap_url)

    async def _make_app(self) -> web.Application:
        app = await super()._make_app()

        @web.middleware
        async def local_capability(
            request: web.Request, handler: Handler
        ) -> web.StreamResponse:
            return await self.authentication.decode(request).dispatch(request, handler)

        async def on_response_prepare(
            request: web.Request, response: web.StreamResponse
        ) -> None:
            # Streaming download/WS handlers prepare before middleware returns.
            BrowserAdmission.secure(response)

        app.middlewares.append(local_capability)
        app.on_response_prepare.append(on_response_prepare)
        return app
