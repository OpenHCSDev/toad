"""Toad as a user runs it in a terminal, which also notes the process id of its comms observer.

Run as a script by ``terminal/test_observer_death.py``: ``observed_app.py PROJECT WIRE_ROOT``.
"""

from pathlib import Path
import sys

from toad.app import ToadApp
from toad.launch_binding import AgentAttached
from toad.cli import run_terminal

from agents import peer


class ObservedApp(ToadApp):

    async def on_mount(self, event):
        event.prevent_default()
        await super().on_mount()
        self.noting = self.set_interval(0.05, self.note_observer)

    def note_observer(self):
        """Once the observer has answered the sidebar, write its process id for the test."""
        access = self.coordination_access
        if access.observation is None or access.sidebar_current is None:
            return
        self.noting.stop()
        pending = Path(self.project_dir) / "observer-pid.new"
        pending.write_text(str(access.observation.process.peer.process.pid))
        pending.replace(Path(self.project_dir) / "observer-pid")


if __name__ == "__main__":
    from agent_comms.launch_root import LaunchRoot
    from toad.comms_root import LocalCoreConnection

    from agent_comms.repo import Checkout

    launch_root = LaunchRoot.from_path(sys.argv[2])
    launch_root.install()
    run_terminal(ObservedApp(project_dir=Checkout(Path(sys.argv[1])), connection=LocalCoreConnection.from_launch(launch_root),
                             agent_binding=AgentAttached(peer("echo"))))
