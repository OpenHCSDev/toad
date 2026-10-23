"""Toad as a user runs it in a terminal, whose conversation raises when it is closed.

Run as a script by ``terminal/test_failed_close.py``: ``failed_close_app.py PROJECT WIRE_ROOT``.
"""

from pathlib import Path
import sys
from unittest.mock import patch

from toad.app import ToadApp
from toad.cli import run_terminal
from toad.widgets.conversation import Conversation
from toad.goal_interaction import GoalSession

from agents import peer
from stylesheets import INSTALLED


class CloseStepFailed(Exception):
    """The controlled failure of the first step of releasing a conversation."""


class FailedCloseApp(ToadApp):
    CSS_PATH = INSTALLED

    async def on_mount(self, event):
        event.prevent_default()
        await super().on_mount()
        self.noting = self.set_interval(0.05, self.break_release)

    def break_release(self):
        """Once a conversation is open, break its release and tell the test."""
        for conversation in self.screen.query(Conversation):
            self.noting.stop()
            (Path(self.project_dir) / "conversation-open").touch()


if __name__ == "__main__":
    from agent_comms.launch_root import LaunchRoot

    LaunchRoot.from_path(sys.argv[2]).install()
    with patch.object(GoalSession, "close", side_effect=CloseStepFailed("goal controls")):
        run_terminal(FailedCloseApp(project_dir=sys.argv[1], agent_data=peer("echo")))
