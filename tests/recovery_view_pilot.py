"""Optional recovery presentation reads only the post-paint gateway DTO."""
from toad.navigation_target import NavigationContext
from runtime_fixture import coordination_update

from toad.navigation_target import channel_target

import asyncio
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import wire
from agent_comms.threads import Thread
from comms_boundary_fixture import coordination_fact
from runtime_fixture import ToadApp
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.side_bar import SideBar, SideBarCollapsible


class PaintProbe(ToadApp):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.painted = 0
        self.paint_times: list[float] = []

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if renderable is not None and screen is self.screen and (not self._batch_count):
            self.painted += 1
            self.paint_times.append(time.perf_counter())
        return result


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-recovery-view-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        comms = wire(root / "wire")
        comms.threads.register(
            Thread(
                "fixture",
                frozenset({"test"}),
                str(root),
                process_identity=ProcessIdentity.capture(os.getpid()),
            )
        )
        app = PaintProbe(project_dir=str(root))
        seen = []
        available = [True]

        async def read(path: Path, thread: str):
            seen.append((app.painted, path, thread))
            if not available[0]:
                return {
                    "schema": 1,
                    "availability": "unavailable",
                    "reason": "gateway_unavailable",
                }
            return {
                "schema": 1,
                "availability": "available",
                "owner": thread,
                "sampledAtMs": 1,
                "current": {
                    "status": "completed",
                    "origin": "wire",
                    "isCurrent": False,
                    "attempt": {
                        "ordinal": 1,
                        "phase": "succeeded",
                        "backendDone": True,
                        "backendProcessExited": True,
                    },
                    "canRetry": False,
                    "publication": "published",
                },
                "lastRecovery": {
                    "kind": "recovered",
                    "attempt": 1,
                    "elapsedMs": 2,
                    "observedAtMs": 3,
                },
                "connectivity": {
                    "owner": "connected",
                    "acpClient": "connected",
                    "observedAtMs": 4,
                },
            }

        with patch("toad.widgets.recovery_view._read_gateway", side_effect=read):
            async with app.run_test(size=(110, 38)) as pilot:
                await pilot.pause()
                view = app.screen.query_one(RecoveryView)
                panel = view.query_ancestor(SideBarCollapsible)
                assert not app.settings.ui.recovery_view
                assert not panel.display and not seen, "Default-off created a gateway read"
                await app.screen.on_coordination_update(coordination_update(str(root / 'wire'), 'fixture'))
                assert view.thread == "fixture"
                started = time.perf_counter()
                painted_before = app.painted
                app.settings.ui.recovery_view = True
                sidebar = app.screen.query_one("#thread-sidebar", SideBar)
                sidebar.reveal()
                panel.collapsed = False
                async with asyncio.timeout(5):
                    while not seen:
                        await pilot.pause(0.02)
                assert seen[0][0] > painted_before, (
                    "Gateway read preceded enabled view's first paint"
                )
                first_paint_ms = (app.paint_times[painted_before] - started) * 1000
                assert seen[0][1] == root / "wire" / ".recovery-viewer" / "gateway.sock"
                assert seen[0][2] == view.thread
                assert "Execution: completed · succeeded" in view.render().plain
                assert "Recovery: recovered" in view.render().plain
                available[0] = False
                view.action_refresh()
                async with asyncio.timeout(5):
                    while "unavailable" not in view.render().plain.lower():
                        await pilot.pause(0.02)
                assert view.render().plain.startswith("Recovery unavailable")
                assert "recovered" not in view.render().plain
                available[0] = True
                view.set_identity("renamed-fixture", root / "wire")
                async with asyncio.timeout(5):
                    while (
                        not seen
                        or seen[-1][2] != "renamed-fixture"
                        or "Recovery: recovered" not in view.render().plain
                    ):
                        await pilot.pause(0.02)
                assert seen[-1][2] == "renamed-fixture"
                assert "Recovery: recovered" in view.render().plain
                app.settings.ui.recovery_view = False
                await pilot.pause()
                assert not panel.display
                assert view.render().plain.startswith("Recovery unavailable")
                reads = len(seen)
                await channel_target("#test").open(NavigationContext(app, app.selected_mode, root, "fixture"))
                await pilot.pause()
                channel_view = app.screen.query_one(RecoveryView)
                assert channel_view.thread == "fixture"
                assert not channel_view.query_ancestor(SideBarCollapsible).display
                assert len(seen) == reads
                app.settings.ui.recovery_view = True
                app.screen.query_one("#thread-sidebar", SideBar).reveal()
                channel_view.query_ancestor(SideBarCollapsible).collapsed = False
                async with asyncio.timeout(5):
                    while len(seen) == reads:
                        await pilot.pause(0.02)
                assert seen[-1][2] == "fixture", (
                    "Channel target was used as a recovery owner"
                )
                assert "Execution: completed" in channel_view.render().plain
                assert app._exception is None
            await asyncio.get_running_loop().shutdown_default_executor()
    print(
        {
            "recovery_view": "default off, post-paint gateway-only read, unavailable/rename/restart",
            "first_painted_frame_ms": round(first_paint_ms, 2),
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
