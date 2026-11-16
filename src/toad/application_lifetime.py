"""Application startup, graceful exit and optional reporting own their lifetime."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import cached_property, partial
from importlib import import_module
import platform
from time import monotonic
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, ClassVar

from agent_comms.nominal.field_codec import AcpSessionId, NoAcpSessionId
from formbridge.operations import OperationKind

from toad import get_version
from toad.version import VersionMonitor
from toad.client.tab_identity.kinds import MailboxTab
from toad.client.tab_identity import TabTargetGone

if TYPE_CHECKING:
    from ssl import SSLContext

    from toad.app import ToadApp


class ApplicationStart(OperationKind):
    """The application's startup: restoring tabs, then attaching its monitors."""


class UsageReport(OperationKind):
    """One opt-in usage event on its way to the external collector."""


class VersionCheck(OperationKind):
    """Asks whether a newer Toad has been released."""


class ProcessTitleUpdate(OperationKind):
    """Names the process off the UI thread."""


class ApplicationExit(OperationKind):
    """Saves the settings in use, then ends the application."""


class UsageReports:
    """All producers use one opt-in policy, identity and external HTTP boundary."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app

    @cached_property
    def tls(self) -> SSLContext:
        # Built once, on the first delivery: loading the CA certificates holds
        # the GIL for 4-14 ms, which blocked the UI thread at every report.
        from httpx import create_ssl_context

        return create_ssl_context()

    def publish(self, event_name: str, **properties: object) -> None:
        self.app.run_operation(UsageReport, partial(self.send, event_name, properties))

    async def send(self, event_name: str, properties: dict[str, object]) -> None:
        await self.app.settings.statistics.collect(partial(self.deliver, event_name, properties))

    async def deliver(self, event_name: str, properties: dict[str, object]) -> None:
        app = self.app
        httpx = await app.preparation.run_thread(import_module, "httpx")

        width, height = app.display_size
        body = {
            "api_key": "phc_mJWPV7GP3ar1i9vxBg2U8aiKsjNgVwum6F6ZggaD4ri",
            "event": event_name,
            "distinct_id": app.settings.anon_id,
            "properties": {"toad_version": get_version(), "term_program": app.terminal_attention.program(),
                           "term_width": width, "term_height": height} | properties,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "os": platform.system(),
        }
        tls = await app.preparation.run_thread(lambda: self.tls)
        try:
            async with httpx.AsyncClient(verify=tls) as client:
                await client.post("https://us.i.posthog.com/i/v0/e/", json=body)
        except httpx.HTTPError:
            # Optional collection cannot prevent normal application use.
            return


class ApplicationStartupObserverAlreadyInstalled(RuntimeError):
    """Only one external observer may await the next application startup."""


class ApplicationStartupHook:
    """One-shot startup observation state owned by the application lifetime."""

    def install(self, observer: Callable[[ApplicationLifetime], None]) -> ApplicationStartupHook:
        return PendingApplicationStartupHook(observer)

    def notify(self, lifetime: ApplicationLifetime) -> ApplicationStartupHook:
        return self


@dataclass(frozen=True)
class PendingApplicationStartupHook(ApplicationStartupHook):
    observer: Callable[[ApplicationLifetime], None]

    def install(self, observer: Callable[[ApplicationLifetime], None]) -> ApplicationStartupHook:
        raise ApplicationStartupObserverAlreadyInstalled(
            "An application startup observer is already installed")

    def notify(self, lifetime: ApplicationLifetime) -> ApplicationStartupHook:
        self.observer(lifetime)
        return ApplicationStartupHook()


class ApplicationLifetime:
    """A confirmed quit and explicit quit share the same save-after-blur path."""

    _startup_hook: ClassVar[ApplicationStartupHook] = ApplicationStartupHook()

    @classmethod
    def observe_next_start(cls, observer: Callable[[ApplicationLifetime], None]) -> None:
        """Install the sole one-shot observer for the next owned startup."""
        cls._startup_hook = cls._startup_hook.install(observer)

    @staticmethod
    def set_process_title(title: str) -> None:
        """Name the terminal application or its CLI server process."""
        import setproctitle

        setproctitle.setproctitle(title)

    def __init__(self, app: ToadApp, resumed_session: AcpSessionId | NoAcpSessionId) -> None:
        self.app = app
        # The agent session the launch asked to resume, if it named one.
        self.resumed_session = resumed_session
        self.quit_warning_deadline = 0.0
        self.usage = UsageReports(app)
        self.version = VersionMonitor()

    def begin(self) -> None:
        """Run start as its own task: it awaits drawn frames, so neither Mount
        (drawn after its batch closes) nor the App's message queue (whose timers
        end delayed updates) may wait on it. The operation records its completion and error."""
        self.app.run_operation(ApplicationStart, self.start)

    async def start(self) -> None:
        type(self)._startup_hook = type(self)._startup_hook.notify(self)
        app = self.app
        if app.saved_settings.ensure_installation():
            app.schedule_ui(partial(self.usage.publish, "toad-install"))
        self.usage.publish("toad-run")
        await self.resumed_session.selected(
            await self.restored_tabs(),
            lambda resumed: partial(self.open_resumed, resumed),
        )()
        await self.show_home_without_tabs()
        app.terminal_attention.attach()
        self.version = app.settings.updates.monitor()
        app.delay_ui(1, partial(app.run_operation, VersionCheck, self.check_version))
        app.run_operation(ProcessTitleUpdate,
                          partial(app.preparation.run_thread, self.set_process_title, "toad"))
        app.update_show_sessions()

    async def restored_tabs(self) -> Callable[[], Awaitable[object]]:
        """Restore the tabs the observed Core saved; the answer opens the last of them."""
        app = self.app
        restored: Callable[[], Awaitable[object]] = self.restore_nothing
        for identity in await app.tab_order.load():
            try:
                restored = partial(app.session_navigation.open,
                                   await identity.restore(app.session_navigation))
            except TabTargetGone as error:
                await app.tab_order.close((identity,))
                app.log_error(f"Removed stale tab {error.identity}: {error.reason}")
        return restored

    async def open_saved_tabs(self) -> None:
        """A switched-to Core's saved tabs, opened as a start opens them."""
        await (await self.restored_tabs())()
        await self.show_home_without_tabs()

    async def show_home_without_tabs(self) -> None:
        if not self.app.tab_order.names:
            await self.app.select_session(self.app.tab_order.home)

    async def restore_nothing(self) -> None:
        """No saved tab came back; the home tab is selected instead."""

    async def open_resumed(self, resumed: AcpSessionId) -> None:
        """The thread's declaration decides how it opens, as from the sidebar."""
        app = self.app
        navigation = await app.preparation.run_thread(partial(self.launch_navigation, resumed))
        await app.session_navigation.new(
            MailboxTab(navigation.thread.incarnation, navigation.root),
            partial(navigation.launch_screen, app),
            original=(navigation.root, navigation.thread.incarnation),
        )

    def launch_navigation(self, resumed: AcpSessionId):
        from toad.navigation_preparation import ThreadNavigationRequest

        request = ThreadNavigationRequest(self.app.coordination_access.observation.observed(),
                                          str(resumed), self.app.project_dir, ())
        return request.read()

    async def check_version(self) -> None:
        await self.version.check(self.app.preparation)

    def confirm_quit(self) -> None:
        now = monotonic()
        if now <= self.quit_warning_deadline:
            self.quit()
        else:
            self.quit_warning_deadline = now + 5.0
            self.app.show_info("Press [b]ctrl+c[/b] again to quit the app", "Do you want to quit?")

    def quit(self) -> None:
        app = self.app
        app.clear_focus()
        # Saving first sends what the user has typed into an open settings form;
        # the app closes only once the file holds the settings in use.
        app.schedule_ui(partial(app.run_operation, ApplicationExit, self.save_and_exit))

    async def save_and_exit(self) -> None:
        await self.app.saved_settings.save_before_exit(self.app.end_application)
