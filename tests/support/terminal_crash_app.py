"""Toad in a terminal whose UI raises a controlled error after its first paint.

Run as a script by ``terminal/test_terminal_crash.py``: ``terminal_crash_app.py PROJECT WIRE_ROOT``.
"""

import sys
from pathlib import Path

from agents import peer
from textual import on
from textual.events import Mount

from toad.app import ToadApp
from toad.cli import run_terminal


class TerminalCrashApp(ToadApp):

    @on(Mount)
    async def on_mount(self, event):
        event.prevent_default()
        await super().on_mount()
        self.call_after_refresh(self.fail_after_paint)

    def fail_after_paint(self):
        raise RecursionError("CONTROLLED_TERMINAL_CAPTURE_PROOF")


if __name__ == "__main__":
    from agent_comms.execution.launch_root import LaunchRoot
    from agent_comms.projects.checkouts import Checkout

    from toad.comms_root import LocalCoreConnection
    from toad.launch_binding import AgentAttached

    launch_root = LaunchRoot.from_path(sys.argv[2])
    launch_root.install()
    run_terminal(TerminalCrashApp(project_dir=Checkout(Path(sys.argv[1])), connection=LocalCoreConnection.from_launch(launch_root),
                                  agent_binding=AgentAttached(peer("echo"))))
