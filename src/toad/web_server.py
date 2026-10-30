"""Authenticated access to the installed textual-serve routes.

A local endpoint listens on loopback TCP and is reached with a bootstrap capability; a
tailnet endpoint listens only on an owner-only unix socket that `tailscale serve`
proxies to, and that proxy supplies the caller's tailnet identity.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shlex
import signal
import socket
import stat
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote, urlsplit

import aiohttp_jinja2
import jinja2
import platformdirs
from agent_comms.field_codec import FieldCodec
from agent_comms.process_claim import ProcessSingleton
from agent_comms.wire_models import WireModel
from aiohttp import web
from pydantic import Field
from textual_serve.server import Server

import toad
from toad.application_lifetime import ApplicationLifetime

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
    def listening(self) -> AbstractContextManager[socket.socket]:
        """The bound, not yet listening, socket this endpoint alone accepts on, held
        for the server's lifetime."""

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

    @contextmanager
    def listening(self) -> Iterator[socket.socket]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            yield listener

    @property
    def cookie_name(self) -> str:
        # Cookies have no port scope; concurrent local servers need distinct names.
        return f"toad_web_session_{self.port}"


@dataclass(frozen=True)
class OwnerOnlyDirectory:
    """A directory only this user can enter, so nobody else can rename or plant its entries.

    platformdirs falls back to /tmp/runtime-UID when /run/user/UID is not writable, and
    another local user can create that path first; the directory is decoded, not trusted.
    """

    path: Path

    @classmethod
    def user_runtime(cls) -> OwnerOnlyDirectory:
        return cls.decode(Path(platformdirs.user_runtime_dir()))

    @classmethod
    def decode(cls, path: Path) -> OwnerOnlyDirectory:
        path.mkdir(mode=0o700, exist_ok=True)
        status = path.lstat()
        if not stat.S_ISDIR(status.st_mode):
            raise RuntimeError(f"{path} is not a directory")
        if status.st_uid != os.getuid() or status.st_mode & 0o077:
            raise RuntimeError(
                f"{path} must be owned by uid {os.getuid()} with mode 0700, "
                f"found uid {status.st_uid} mode {stat.S_IMODE(status.st_mode):o}"
            )
        return cls(path)


@dataclass(frozen=True)
class TailnetBrowserEndpoint(BrowserEndpoint):
    """A 0600 unix socket that only `tailscale serve` (root) and its owner can open.

    No TCP listener exists, so no local process can forge the Tailscale-User-Login
    header: the only peer that reaches the routes is the proxy that sets it.
    """

    dns_name: str
    https_port: int
    directory: OwnerOnlyDirectory

    @property
    def url(self) -> str:
        if self.https_port == 443:
            return f"https://{self.dns_name}"
        return f"https://{self.dns_name}:{self.https_port}"

    @property
    def socket_path(self) -> Path:
        return self.directory.path / f"toad-serve-{self.https_port}.sock"

    @property
    def lock_path(self) -> Path:
        return self.directory.path / f"toad-serve-{self.https_port}.lock"

    @property
    def listens_on(self) -> str:
        return (
            f"unix:{self.socket_path} "
            f"(tailscale serve --bg --https={self.https_port} unix:{self.socket_path})"
        )

    @contextmanager
    def listening(self) -> Iterator[socket.socket]:
        """Holding the claim is being the live server, so only its holder touches the path.

        A connect probe cannot tell a dead server from one that has bound but not yet
        listened: both refuse.
        """
        with (
            ProcessSingleton(self.lock_path).claimed(),
            socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener,
        ):
            self.socket_path.unlink(missing_ok=True)
            listener.bind(str(self.socket_path))
            try:
                # Nothing can connect before listen(), so the mode is set before any peer
                # exists; nobody else can enter the directory to swap the path.
                self.socket_path.chmod(0o600)
                yield listener
            finally:
                self.socket_path.unlink(missing_ok=True)


class ViewportTemplates(jinja2.FileSystemLoader):
    """The vendor's own pages, plus the viewport its head lacks.

    Without it phones lay the page out at desktop width; the rest of the page stays
    the reviewed textual-serve 1.1.3 template, read from the package.
    """

    VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />'

    def get_source(
        self, environment: jinja2.Environment, template: str
    ) -> tuple[str, str, Callable[[], bool]]:
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


class TailscaleStatus(WireModel):
    """Only the required native status fields; unrelated status data stays opaque."""

    Self: TailscaleNode
    User: dict[str, TailscaleUser]

    def authentication(
        self, https_port: int, directory: OwnerOnlyDirectory
    ) -> TailnetBrowserAuthentication:
        return TailnetBrowserAuthentication(
            TailnetBrowserEndpoint(
                self.Self.DNSName.rstrip("."), https_port, directory
            ),
            self.User[str(self.Self.UserID)],
        )


@dataclass(frozen=True)
class TailnetBrowserAuthentication(BrowserAuthentication):
    """The tailnet login `tailscale serve` attaches to each request is the credential."""

    endpoint: TailnetBrowserEndpoint
    owner: TailscaleUser

    @classmethod
    def from_status(cls, https_port: int) -> TailnetBrowserAuthentication:
        """This node's tailnet name and owning login, read from Tailscale itself."""
        result = subprocess.run(
            ("tailscale", "status", "--json", "--self"),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = FieldCodec.decode(TailscaleStatus, FieldCodec.parse(result.stdout))
        return status.authentication(https_port, OwnerOnlyDirectory.user_runtime())

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

    @classmethod
    def run_toad(
        cls, authentication: BrowserAuthentication, toad_args: tuple[str, ...]
    ) -> None:
        """Each browser tab runs `toad TOAD ARGS`, or `toad .` when none are given."""
        command = shlex.join(
            [sys.executable, "-m", toad.__name__, *(toad_args or (".",))]
        )
        server = cls(command, authentication, title="Toad")
        ApplicationLifetime.set_process_title("toad serve")
        server.serve()

    def serve(self, debug: bool = False) -> None:
        """Mirrors textual-serve 1.1.3 `Server.serve`, listening on the endpoint's socket.

        The vendor binds TCP host:port; a tailnet endpoint has no TCP listener at all.
        """
        self.debug = debug
        self.initialize_logging()
        loop = asyncio.new_event_loop()
        loop.add_signal_handler(signal.SIGINT, self.request_exit)
        loop.add_signal_handler(signal.SIGTERM, self.request_exit)
        if self.debug:
            logging.getLogger("textual-serve").info(
                "Running in debug mode. You may use textual dev tools."
            )
        with self.authentication.endpoint.listening() as listener:
            web.run_app(
                self._make_app(),
                sock=listener,
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
