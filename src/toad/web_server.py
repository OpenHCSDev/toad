"""Authenticated access to the installed textual-serve routes, bound to loopback.

A local endpoint is reached directly with a bootstrap capability; a tailnet endpoint is
reached through `tailscale serve`, which supplies the caller's tailnet identity.
"""

from __future__ import annotations

import json
import logging
import secrets
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote, urlsplit

from aiohttp import web
from textual_serve.server import Server

type Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@dataclass(frozen=True)
class BrowserEndpoint(ABC):
    """Where the server binds (always loopback) and the origin browsers address."""

    host: str
    port: int

    def __post_init__(self) -> None:
        if self.host not in {"localhost", "127.0.0.1"} or not 1 <= self.port <= 65535:
            raise ValueError(
                "Browser serving requires a loopback host and a valid port"
            )

    @property
    @abstractmethod
    def url(self) -> str:
        """The origin a browser uses for pages and the websocket."""

    @property
    def authority(self) -> str:
        return urlsplit(self.url).netloc

    def addresses(self, request: web.Request) -> bool:
        """The request names this origin, and a websocket comes from it."""
        hosts = request.headers.getall("Host", [])
        origins = request.headers.getall("Origin", [])
        if hosts != [self.authority]:
            return False
        if request.path == "/ws" and origins != [self.url]:
            return False
        return not origins or origins == [self.url]


@dataclass(frozen=True)
class LocalBrowserEndpoint(BrowserEndpoint):
    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def cookie_name(self) -> str:
        # Cookies have no port scope; concurrent local servers need distinct names.
        return f"toad_web_session_{self.port}"


@dataclass(frozen=True)
class TailnetBrowserEndpoint(BrowserEndpoint):
    """Served by `tailscale serve --https=PORT`, which keeps Host and Origin."""

    origin: str

    @property
    def url(self) -> str:
        return self.origin


class BrowserAccess(ABC):
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


class RejectedBrowserAccess(BrowserAccess):
    async def respond(
        self, request: web.Request, handler: Handler
    ) -> web.StreamResponse:
        return web.Response(status=403)


class AuthenticatedBrowserAccess(BrowserAccess):
    async def respond(
        self, request: web.Request, handler: Handler
    ) -> web.StreamResponse:
        return await handler(request)


@dataclass(frozen=True)
class BootstrapBrowserAccess(BrowserAccess):
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


class BrowserAuthentication(ABC):
    endpoint: BrowserEndpoint

    def decode(self, request: web.Request) -> BrowserAccess:
        """Decode external Host, Origin and credentials before any route handler."""
        if not self.endpoint.addresses(request):
            return RejectedBrowserAccess()
        return self.credential(request)

    @abstractmethod
    def credential(self, request: web.Request) -> BrowserAccess: ...

    @property
    @abstractmethod
    def entry_url(self) -> str:
        """What the operator opens; printed once at startup."""


@dataclass(frozen=True)
class TailnetBrowserAuthentication(BrowserAuthentication):
    """The tailnet login `tailscale serve` attaches to each request is the credential."""

    endpoint: TailnetBrowserEndpoint
    login: str

    @classmethod
    def from_status(cls, host: str, port: int, tailnet_port: int) -> TailnetBrowserAuthentication:
        """This node's tailnet name and owning login, read from Tailscale itself."""
        status = json.loads(subprocess.run(
            ("tailscale", "status", "--json", "--self"), check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout)
        node = status["Self"]
        origin = f"https://{node['DNSName'].rstrip('.')}:{tailnet_port}"
        login = status["User"][str(node["UserID"])]["LoginName"]
        return cls(TailnetBrowserEndpoint(host, port, origin), login)

    def credential(self, request: web.Request) -> BrowserAccess:
        if request.headers.getall("Tailscale-User-Login", []) == [self.login]:
            return AuthenticatedBrowserAccess()
        return RejectedBrowserAccess()

    @property
    def entry_url(self) -> str:
        return f"{self.endpoint.url}/"


@dataclass(frozen=True)
class LocalBrowserAuthentication(BrowserAuthentication):
    endpoint: LocalBrowserEndpoint
    capability: str = field(
        default_factory=lambda: secrets.token_urlsafe(32), repr=False
    )

    @property
    def entry_url(self) -> str:
        return f"{self.endpoint.url}/?token={quote(self.capability)}"

    def accepts(self, candidate: str) -> bool:
        # Compare bytes so an external non-ASCII credential is rejected, not a 500.
        return secrets.compare_digest(
            candidate.encode("utf-8", errors="surrogatepass"),
            self.capability.encode("ascii"),
        )

    def credential(self, request: web.Request) -> BrowserAccess:
        token = request.query.get("token")
        if request.path == "/" and token is not None:
            if request.method == "GET" and self.accepts(token):
                return BootstrapBrowserAccess(self)
            return RejectedBrowserAccess()
        if self.accepts(request.cookies.get(self.endpoint.cookie_name, "")):
            return AuthenticatedBrowserAccess()
        return RejectedBrowserAccess()


class ToadWebServer(Server):
    """Keep the vendor server/child path; check local access before every route."""

    def __init__(
        self,
        command: str,
        authentication: BrowserAuthentication,
        *,
        title: str | None = None,
    ) -> None:
        if version("textual-serve") != "1.1.3":
            raise RuntimeError("Browser serving requires reviewed textual-serve 1.1.3")
        endpoint = authentication.endpoint
        super().__init__(
            command, host=endpoint.host, port=endpoint.port, title=title,
            public_url=endpoint.url,
            # The vendor page lacks a viewport, so phones laid it out at desktop width.
            templates_path=Path(__file__).parent / "web_templates",
        )
        self.authentication = authentication

    def initialize_logging(self) -> None:
        super().initialize_logging()
        # Access URLs must never record the bootstrap bearer credential.
        logging.getLogger("aiohttp.access").disabled = True

    async def on_startup(self, app: web.Application) -> None:
        self.console.print("Toad browser (keep this URL private):")
        self.console.print(self.authentication.entry_url)

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
            BrowserAccess.secure(response)

        app.middlewares.append(local_capability)
        app.on_response_prepare.append(on_response_prepare)
        return app
