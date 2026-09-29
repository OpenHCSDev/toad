"""Actual terminal driver retains a controlled UI failure after terminal exit."""
import inspect
import os
from pathlib import Path
import sys

from agent_comms.comms import Comms
from toad.app import ToadApp
from toad.cli import run_terminal


class TerminalCrashApp(ToadApp):
    CSS_PATH = Path(inspect.getfile(ToadApp)).with_name("toad.tcss")

    async def on_mount(self, event):
        event.prevent_default()
        await super().on_mount()
        self.call_after_refresh(self.fail_after_paint)

    def fail_after_paint(self):
        raise RecursionError("CONTROLLED_TERMINAL_CAPTURE_PROOF")


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                     XDG_STATE_HOME=str(root / "state"),
                     XDG_CONFIG_HOME=str(root / "config"),
                     XDG_DATA_HOME=str(root / "data"))
    Comms(root / "wire").messaging.initialize_private_initial_protocol()
    run_terminal(TerminalCrashApp(project_dir=str(root)))
