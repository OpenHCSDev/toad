"""Toad as a user runs it in a terminal, whose conversation raises when it is closed.

Run as a script by ``terminal/test_failed_close.py``: ``failed_close_app.py PROJECT``.
"""

from pathlib import Path
import sys

from toad.app import ToadApp
from toad.session_scope import AgentAttached
from toad.cli import run_terminal
from toad.widgets.conversation import Conversation

from agents import peer
from stylesheets import INSTALLED


class CloseStepFailed(Exception):
    """The controlled failure of the first step of releasing a conversation."""


def fail():
    raise CloseStepFailed("goal controls")


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
            conversation.goal_controls.close = fail
            (Path(self.project_dir) / "conversation-open").touch()


if __name__ == "__main__":
    run_terminal(FailedCloseApp(project_dir=sys.argv[1], agent_binding=AgentAttached(peer("echo"))))
