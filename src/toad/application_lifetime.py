"""Application startup, graceful exit and optional reporting own their lifetime."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
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

    def publish(self, event_name: str, **properties: object):
        return self.app.run_worker(partial(self.send, event_name, properties), exit_on_error=False)

    async def send(self, event_name: str, properties: dict[str, object]) -> None:
        await self.app.settings.statistics.collect(partial(self.deliver, event_name, properties))

    async def deliver(self, event_name: str, properties: dict[str, object]) -> None:
        app = self.app
        import httpx
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
        try:
            async with httpx.AsyncClient() as client:
                await client.post("https://us.i.posthog.com/i/v0/e/", json=body)
        except httpx.HTTPError:
            # Optional collection cannot prevent normal application use.
            return


class ApplicationLifetime:
    """A confirmed quit and explicit quit share the same save-after-blur path."""

    def __init__(self, app: ToadApp, initial_mode: str | None) -> None:
        self.app = app
        self.initial_mode = initial_mode
        self.quit_warning_deadline = 0.0
        self.usage = UsageReports(app)
        self.version = VersionMonitor()

    async def start(self) -> None:
        app = self.app
        if app.settings.ensure_installation():
            app.call_later(self.usage.publish, "toad-install")
        self.usage.publish("toad-run")
        if self.initial_mode:
            await app.select_session(self.initial_mode)
        else:
            await app.session_navigation.new(app.session_navigation.default_source)
        app.terminal_attention.attach()
        app.set_timer(1, self.check_version)
        from toad.cli import set_process_title
        app.run_worker(partial(set_process_title, "toad"), thread=True, exit_on_error=False)
        app.update_show_sessions()

    def check_version(self) -> None:
        self.app.run_worker(self.version.check, exit_on_error=False)

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
        # Textual queues blur ahead of this callback. Await saving before exit;
        # a fixed timer never proves the focused editor has committed its value.
        app.call_later(self.save_and_exit)

    async def save_and_exit(self) -> None:
        await self.app.settings.save_before_exit(self.app.exit)
