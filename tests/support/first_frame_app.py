"""Toad as a user runs it in a terminal, plus read-only notes on the first frame and the prompt.

Run as a script by ``terminal/test_first_frame.py``: ``first_frame_app.py PROJECT``.
"""
import json
from importlib.resources import files
from pathlib import Path
import shlex
import sys
from time import monotonic_ns

from textual.widgets import Input
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.screens.workspace import WorkspaceScreen
from toad.widgets.prompt import Prompt
from toad.widgets.slash_complete import SlashComplete


class FrameApp(ToadApp):
    # Textual resolves a subclass's relative paths beside the subclass, so name the installed ones.
    CSS_PATH = [files("toad").joinpath("toad.tcss"), files("toad").joinpath("screens/comms.tcss")]

    def _display(self, screen, renderable):
        # Observe the real owner/driver barrier; never replace display, flush,
        # agent startup, protocol, frame state or compositor with a test double.
        if isinstance(screen, WorkspaceScreen) and not screen.frame_presentation.ready:
            screen.frame_presentation.defer(screen, self.record_frame)
        super()._display(screen, renderable)
        if isinstance(screen, WorkspaceScreen):
            if prompt := screen.query_one_optional(Prompt):
                slash_input = prompt.slash_complete.query_one_optional(Input)
                state = json.dumps({
                    "text": prompt.text, "agent_ready": prompt.agent_ready, "editor_focused": prompt.prompt_text_area.has_focus,
                    "slash_open": any(popup.is_open for popup in prompt.query(SlashComplete)),
                    "slash_focused": slash_input is not None and slash_input.has_focus,
                    "slash_query": "" if slash_input is None else slash_input.value,
                })
                # Readers poll this file; replace it whole so they never see half of it.
                pending = Path(self.project_dir) / "current-ui.json.new"
                pending.write_text(state)
                pending.replace(Path(self.project_dir) / "current-ui.json")

    def record_frame(self):
        frame = self.screen.frame_presentation
        with (Path(self.project_dir) / "frames.jsonl").open("a") as stream:
            stream.write(json.dumps({
                "ready": frame.ready, "mode": self.current_mode,
                "driver": type(self._driver).__name__, "time_ns": monotonic_ns(),
            }) + "\n")


if __name__ == "__main__":
    peer = Path(__file__).with_name("peers") / "first_frame.py"
    app = FrameApp(project_dir=sys.argv[1], agent_data=AgentDefinition.decode({
        "name": "Physical frame peer", "identity": "frame-acceptance",
        "short_name": "Frame", "protocol": "acp",
        "run_command": {"*": shlex.join([sys.executable, str(peer)])},
    }))
    app.run()
