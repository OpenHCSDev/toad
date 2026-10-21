"""Toad as a user runs it in a terminal, which also notes the process id of its comms observer.

Run as a script by ``terminal/test_observer_death.py``: ``observed_app.py PROJECT``.
"""

from pathlib import Path
import sys

from toad.app import ToadApp
from toad.session_scope import AgentAttached
from toad.cli import run_terminal

from agents import peer
from stylesheets import INSTALLED


class ObservedApp(ToadApp):
    CSS_PATH = INSTALLED

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
        pending.write_text(str(access.observation.process.process.pid))
        pending.replace(Path(self.project_dir) / "observer-pid")


if __name__ == "__main__":
    run_terminal(ObservedApp(project_dir=sys.argv[1], agent_binding=AgentAttached(peer("echo"))))
