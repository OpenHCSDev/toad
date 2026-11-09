"""Toad in a terminal whose UI raises a controlled error after its first paint.

Run as a script by ``terminal/test_terminal_crash.py``: ``terminal_crash_app.py PROJECT WIRE_ROOT``.
"""

from pathlib import Path
import sys

from toad.app import ToadApp
from toad.cli import run_terminal

from agents import peer
from textual import on
from textual.events import Mount


class TerminalCrashApp(ToadApp):

    @on(Mount)
    async def on_mount(self, event):
        event.prevent_default()
        await super().on_mount()
        self.call_after_refresh(self.fail_after_paint)

    def fail_after_paint(self):
        raise RecursionError("CONTROLLED_TERMINAL_CAPTURE_PROOF")


if __name__ == "__main__":
    from agent_comms.launch_root import LaunchRoot
    from toad.comms_root import LocalCoreConnection

    from agent_comms.projects.checkouts import Checkout
    from toad.launch_binding import AgentAttached

    launch_root = LaunchRoot.from_path(sys.argv[2])
    launch_root.install()
    run_terminal(TerminalCrashApp(project_dir=Checkout(Path(sys.argv[1])), connection=LocalCoreConnection.from_launch(launch_root),
                                  agent_binding=AgentAttached(peer("echo"))))
