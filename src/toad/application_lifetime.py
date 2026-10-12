"""Application startup, graceful exit and optional reporting own their lifetime."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from importlib import import_module
import platform
from time import monotonic
from typing import TYPE_CHECKING

from toad.version import VersionMonitor

if TYPE_CHECKING:
    from toad.app import ToadApp


class UsageReports:
    """All producers use one opt-in policy, identity and external HTTP boundary."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        # Built once, on the first delivery: loading the CA certificates holds
        # the GIL for 4-14 ms, which blocked the UI thread at every report.
        self._tls = None

    def publish(self, event_name: str, **properties: object):
        return self.app.run_worker(partial(self.send, event_name, properties))

    async def send(self, event_name: str, properties: dict[str, object]) -> None:
        await self.app.settings.statistics.collect(partial(self.deliver, event_name, properties))

    async def deliver(self, event_name: str, properties: dict[str, object]) -> None:
        app = self.app
        httpx = await app.preparation.run_thread(import_module, "httpx")
        from toad import get_version

        width, height = app.size
        body = {
            "api_key": "phc_mJWPV7GP3ar1i9vxBg2U8aiKsjNgVwum6F6ZggaD4ri",
            "event": event_name,
            "distinct_id": app.settings.anon_id,
            "properties": {"toad_version": get_version(), "term_program": app.terminal_attention.program,
                           "term_width": width, "term_height": height} | properties,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "os": platform.system(),
        }
        if self._tls is None:
            self._tls = await app.preparation.run_thread(httpx.create_ssl_context)
        try:
            async with httpx.AsyncClient(verify=self._tls) as client:
                await client.post("https://us.i.posthog.com/i/v0/e/", json=body)
        except httpx.HTTPError:
            # Optional collection cannot prevent normal application use.
            return


class ApplicationLifetime:
    """A confirmed quit and explicit quit share the same save-after-blur path."""

    @staticmethod
    def set_process_title(title: str) -> None:
        """Name the terminal application or its CLI server process."""
        import setproctitle

        setproctitle.setproctitle(title)

    def __init__(self, app: ToadApp, initial_mode: str | None) -> None:
        self.app = app
        self.initial_mode = initial_mode
        self.quit_warning_deadline = 0.0
        self.usage = UsageReports(app)
        self.version = VersionMonitor()

    async def start(self) -> None:
        app = self.app
        if app.saved_settings.ensure_installation():
            app.call_later(self.usage.publish, "toad-install")
        self.usage.publish("toad-run")
        if self.initial_mode:
            await app.select_session(self.initial_mode)
        else:
            await app.session_navigation.new(app.session_navigation.default_source)
        app.terminal_attention.attach()
        app.set_timer(1, self.check_version)
        app.run_worker(partial(self.set_process_title, "toad"), thread=True)
        app.update_show_sessions()

    def check_version(self) -> None:
        self.app.run_worker(partial(self.version.check, self.app.preparation.run_thread))

    def confirm_quit(self) -> None:
        now = monotonic()
        if now <= self.quit_warning_deadline:
            self.quit()
        else:
            self.quit_warning_deadline = now + 5.0
            self.app.notify("Press [b]ctrl+c[/b] again to quit the app", title="Do you want to quit?")

    def quit(self) -> None:
        app = self.app
        app.screen.set_focus(None)
        # Saving first sends what the user has typed into an open settings form;
        # the app closes only once the file holds the settings in use.
        app.call_later(self.save_and_exit)

    async def save_and_exit(self) -> None:
        await self.app.saved_settings.save_before_exit(self.app.exit)
