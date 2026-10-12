"""Toad in a terminal whose UI raises a controlled error after its first paint.

Run as a script by ``terminal/test_terminal_crash.py``: ``terminal_crash_app.py PROJECT``.
"""

import sys

from toad.app import ToadApp
from toad.cli import run_terminal

from stylesheets import INSTALLED


class TerminalCrashApp(ToadApp):
    CSS_PATH = INSTALLED

    async def on_mount(self, event):
        event.prevent_default()
        await super().on_mount()
        self.call_after_refresh(self.fail_after_paint)

    def fail_after_paint(self):
        raise RecursionError("CONTROLLED_TERMINAL_CAPTURE_PROOF")


if __name__ == "__main__":
    run_terminal(TerminalCrashApp(project_dir=sys.argv[1]))
