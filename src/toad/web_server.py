"""Authenticated access to the installed textual-serve routes.

A local endpoint listens on loopback TCP and is reached with a bootstrap capability; a
tailnet endpoint listens only on an owner-only unix socket that `tailscale serve`
proxies to, and that proxy supplies the caller's tailnet identity.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import signal
import socket
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote, urlsplit

import aiohttp_jinja2
import jinja2
import platformdirs
from agent_comms.field_codec import FieldCodec, boundary_decoder
from agent_comms.wire_models import WireModel
from aiohttp import web
from pydantic import Field
from textual_serve.server import Server

type Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class BrowserEndpoint(ABC):
    """Where the server listens and the origin browsers address."""

    @property
    @abstractmethod
    def url(self) -> str:
        """The origin a browser uses for pages and the websocket."""

    @property
    @abstractmethod
    def listens_on(self) -> str:
        """Where the listening socket is, printed once at startup."""

    @abstractmethod
    def listening_socket(self) -> socket.socket:
        """The bound, not yet listening, socket this endpoint alone accepts on."""

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
    host: str
    port: int

    def __post_init__(self) -> None:
        if self.host not in {"localhost", "127.0.0.1"} or not 1 <= self.port <= 65535:
            raise ValueError(
                "Browser serving requires a loopback host and a valid port"
            )

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def listens_on(self) -> str:
        return self.url

    def listening_socket(self) -> socket.socket:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        return listener

    @property
    def cookie_name(self) -> str:
        # Cookies have no port scope; concurrent local servers need distinct names.
        return f"toad_web_session_{self.port}"


@dataclass(frozen=True)
class TailnetBrowserEndpoint(BrowserEndpoint):
    """A 0600 unix socket that only `tailscale serve` (root) and its owner can open.

    No TCP listener exists, so no local process can forge the Tailscale-User-Login
    header: the only peer that reaches the routes is the proxy that sets it.
    """

    origin: str
    https_port: int
    socket_path: Path

    @classmethod
    def served_at(cls, origin: str, https_port: int) -> TailnetBrowserEndpoint:
        runtime = Path(platformdirs.user_runtime_dir("toad", ensure_exists=True))
        return cls(origin, https_port, runtime / f"serve-{https_port}.sock")

    @property
    def url(self) -> str:
        return self.origin

    @property
    def listens_on(self) -> str:
        return (
            f"unix:{self.socket_path} "
            f"(tailscale serve --bg --https={self.https_port} unix:{self.socket_path})"
        )

    def listening_socket(self) -> socket.socket:
        self.release_stale_socket()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_path))
        # Nothing can connect before listen(), so the mode is set before any peer exists.
        self.socket_path.chmod(0o600)
        return listener

    def release_stale_socket(self) -> None:
        """A path left by a dead server is removed; a live server keeps it and we fail."""
        if not self.socket_path.exists():
            return
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(str(self.socket_path))
        except ConnectionRefusedError:
            self.socket_path.unlink()
        else:
            raise RuntimeError(f"Another toad serve already listens on {self.socket_path}")
        finally:
            probe.close()


class ViewportTemplates(jinja2.FileSystemLoader):
    """The vendor's own pages, plus the viewport its head lacks.

    Without it phones lay the page out at desktop width; the rest of the page stays
    the reviewed textual-serve 1.1.3 template, read from the package.
    """

    VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />'

    def get_source(
        self, environment: jinja2.Environment, template: str
    ) -> tuple[str, str | None, Callable[[], bool] | None]:
        source, filename, uptodate = super().get_source(environment, template)
        head, marker, rest = source.partition("<head>")
        if not marker:
            raise RuntimeError(f"textual-serve template {template} has no <head>")
        return f"{head}<head>\n    {self.VIEWPORT}{rest}", filename, uptodate


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

    @classmethod
    @boundary_decoder
    def from_option(
        cls, host: str, port: int, tailnet_port: int | None
    ) -> BrowserAuthentication:
        """Decode the optional CLI port once into the authentication family."""
        if tailnet_port is None:
            return LocalBrowserAuthentication(LocalBrowserEndpoint(host, port))
        return TailnetBrowserAuthentication.from_status(tailnet_port)

    @property
    @abstractmethod
    def entry_url(self) -> str:
        """What the operator opens; printed once at startup."""


class TailscaleUser(WireModel):
    """The external profile's login is the identity Serve places on requests."""

    LoginName: str = Field(min_length=1)


class TailscaleNode(WireModel):
    DNSName: str = Field(min_length=1)
    UserID: int

    def origin(self, port: int) -> str:
        authority = self.DNSName.rstrip(".")
        if port != 443:
            authority = f"{authority}:{port}"
        return f"https://{authority}"


class TailscaleStatus(WireModel):
    """Only the required native status fields; unrelated status data stays opaque."""

    Self: TailscaleNode
    User: dict[str, TailscaleUser]

    def authentication(self, tailnet_port: int) -> TailnetBrowserAuthentication:
        return TailnetBrowserAuthentication(
            TailnetBrowserEndpoint.served_at(self.Self.origin(tailnet_port), tailnet_port),
            self.User[str(self.Self.UserID)],
        )


@dataclass(frozen=True)
class TailnetBrowserAuthentication(BrowserAuthentication):
    """The tailnet login `tailscale serve` attaches to each request is the credential."""

    endpoint: TailnetBrowserEndpoint
    owner: TailscaleUser

    @classmethod
    def from_status(cls, tailnet_port: int) -> TailnetBrowserAuthentication:
        """This node's tailnet name and owning login, read from Tailscale itself."""
        result = subprocess.run(
            ("tailscale", "status", "--json", "--self"), check=True,
            capture_output=True, text=True, timeout=10,
        )
        status = FieldCodec.decode(TailscaleStatus, FieldCodec.parse(result.stdout))
        return status.authentication(tailnet_port)

    def credential(self, request: web.Request) -> BrowserAccess:
        if request.headers.getall("Tailscale-User-Login", []) == [self.owner.LoginName]:
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
        # host and port stay the vendor defaults: serve() listens on the endpoint's socket.
        super().__init__(command, title=title, public_url=endpoint.url)
        self.authentication = authentication

    def serve(self, debug: bool = False) -> None:
        """Listen only on the endpoint's socket; the vendor's serve binds TCP host:port."""
        self.debug = debug
        self.initialize_logging()
        loop = asyncio.new_event_loop()
        loop.add_signal_handler(signal.SIGINT, self.request_exit)
        loop.add_signal_handler(signal.SIGTERM, self.request_exit)
        web.run_app(
            self._make_app(),
            sock=self.authentication.endpoint.listening_socket(),
            handle_signals=False,
            loop=loop,
            print=lambda *args: None,
        )

    def initialize_logging(self) -> None:
        super().initialize_logging()
        # Access URLs must never record the bootstrap bearer credential.
        logging.getLogger("aiohttp.access").disabled = True

    async def on_startup(self, app: web.Application) -> None:
        self.console.print("Toad browser (keep this URL private):")
        self.console.print(self.authentication.entry_url)
        self.console.print(f"Listening on {self.authentication.endpoint.listens_on}")

    async def _make_app(self) -> web.Application:
        app = await super()._make_app()
        aiohttp_jinja2.setup(app, loader=ViewportTemplates(self.templates_path))

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
