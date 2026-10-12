"""Textual-facing: the optional recovery view (a Static in a sidebar panel) is hidden by default, reads the gateway only after it has been painted, and follows the thread's identity."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from support.stylesheets import INSTALLED
from support.textual_steps import coordination_update
from toad.app import ToadApp
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.preferences import SETTINGS


class PaintCounter(ToadApp):
    """The application, counting the frames it has painted on its current screen."""

    CSS_PATH = INSTALLED

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.painted = 0

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if renderable is not None and screen is self.screen and not self._batch_count:
            self.painted += 1
        return result


AVAILABLE = {
    "schema": 1, "availability": "available", "sampledAtMs": 1,
    "current": {"status": "completed", "origin": "wire", "isCurrent": False,
                "attempt": {"ordinal": 1, "phase": "succeeded", "backendDone": True, "backendProcessExited": True},
                "canRetry": False, "publication": "published"},
    "lastRecovery": {"kind": "recovered", "attempt": 1, "elapsedMs": 2, "observedAtMs": 3},
    "connectivity": {"owner": "connected", "acpClient": "connected", "observedAtMs": 4},
}


@dataclass
class Gateway:
    """What the recovery view asked of the gateway, and what the gateway answers."""

    app: PaintCounter | None = None
    available: bool = True
    seen: list = field(default_factory=list)

    async def read(self, path: Path, thread: str):
        self.seen.append((self.app.painted, path, thread))
        if not self.available:
            return {"schema": 1, "availability": "unavailable", "reason": "gateway_unavailable"}
        return {**AVAILABLE, "owner": thread}


@asynccontextmanager
async def recovery_session(workspace):
    workspace.thread("fixture", "test", running=True)
    gateway = Gateway()
    with patch("agent_comms.recovery_gateway_client.read_gateway_projection", side_effect=gateway.read):
        async with workspace.app(size=(110, 38), application=PaintCounter) as ui:
            app, _pilot = ui.textual
            gateway.app = app
            # The sidebar mounts its panels when it is first shown.
            sidebar = app.selected_session.query_one("#thread-sidebar", SideBar)
            sidebar.reveal()
            await sidebar.wait_content_ready()
            view = app.selected_session.query_one(RecoveryView)
            yield ui, app, view, view.query_ancestor(SideBarCollapsible), gateway


async def enable_and_reveal(app, panel):
    app.saved_settings.set(SETTINGS.ui.recovery_view, True)
    app.selected_session.query_one("#thread-sidebar", SideBar).reveal()
    panel.collapsed = False


async def test_recovery_view_is_off_by_default_and_reads_nothing(workspace):
    async with recovery_session(workspace) as (ui, app, view, panel, gateway):
        assert not app.settings.ui.recovery_view
        assert not panel.display and not gateway.seen, "Default-off created a gateway read"


async def test_enabled_recovery_view_reads_the_gateway_only_after_it_is_painted(workspace):
    async with recovery_session(workspace) as (ui, app, view, panel, gateway):
        await app.selected_session.on_coordination_update(coordination_update(workspace.roots.wire, 'fixture'))
        assert view.thread == "fixture"
        painted_before = app.painted
        await enable_and_reveal(app, panel)
        await ui.until(lambda: gateway.seen, why="the first gateway read")
        assert gateway.seen[0][0] > painted_before, "Gateway read preceded enabled view's first paint"
        assert gateway.seen[0][1] == workspace.roots.wire / ".recovery-viewer" / "gateway.sock"
        assert gateway.seen[0][2] == view.thread
        await ui.until(lambda: "Execution: completed · succeeded" in view.render().plain, why="the execution line")
        assert "Recovery: recovered" in view.render().plain


async def test_an_unavailable_gateway_is_shown_as_unavailable_and_a_rename_reads_again(workspace):
    async with recovery_session(workspace) as (ui, app, view, panel, gateway):
        await app.selected_session.on_coordination_update(coordination_update(workspace.roots.wire, 'fixture'))
        await enable_and_reveal(app, panel)
        await ui.until(lambda: "Recovery: recovered" in view.render().plain, why="the first read")
        gateway.available = False
        view.action_refresh()
        await ui.until(lambda: "unavailable" in view.render().plain.lower(), why="the unavailable text")
        assert view.render().plain.startswith("Recovery unavailable")
        assert "recovered" not in view.render().plain
        gateway.available = True
        view.set_identity("renamed-fixture", workspace.roots.wire)
        await ui.until(lambda: gateway.seen[-1][2] == "renamed-fixture" and "Recovery: recovered" in view.render().plain,
                       why="the renamed thread's read")


async def test_turning_the_view_off_hides_it_and_a_channel_tab_reads_its_owner_thread(workspace):
    async with recovery_session(workspace) as (ui, app, view, panel, gateway):
        await app.selected_session.on_coordination_update(coordination_update(workspace.roots.wire, 'fixture'))
        await enable_and_reveal(app, panel)
        await ui.until(lambda: "Recovery: recovered" in view.render().plain, why="the first read")
        app.saved_settings.set(SETTINGS.ui.recovery_view, False)
        await ui.step()
        assert not panel.display
        assert view.render().plain.startswith("Recovery unavailable")
        reads = len(gateway.seen)
        await ui.open_channel("#test", actor="fixture")
        channel_view = app.selected_session.query_one(RecoveryView)
        assert channel_view.thread == "fixture"
        assert not channel_view.query_ancestor(SideBarCollapsible).display
        assert len(gateway.seen) == reads
        await enable_and_reveal(app, channel_view.query_ancestor(SideBarCollapsible))
        await ui.until(lambda: len(gateway.seen) > reads, why="the channel tab's read")
        assert gateway.seen[-1][2] == "fixture", "Channel target was used as a recovery owner"
        await ui.until(lambda: "Execution: completed" in channel_view.render().plain, why="the channel tab's text")
