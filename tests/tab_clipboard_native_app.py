"""Installed Toad/LinuxDriver copy path driven by an actual terminal key."""

import json
import os
from pathlib import Path
from typing import ClassVar

from textual.screen import Screen

import toad
from toad.app import ToadApp
from toad.widgets.prompt import PromptTextArea

PAYLOAD = "Complete native clipboard café 界\n" * 2400


class CopyApp(ToadApp):
    CSS_PATH: ClassVar = [
        Path(toad.__file__).parent / "toad.tcss",
        Path(toad.__file__).parent / "screens/comms.tcss",
    ]

    async def on_ready(self) -> None:
        self.paste_target = PromptTextArea(simple_input=True)
        await self.push_screen(Screen())
        await self.screen.mount(self.paste_target)
        self.screen.set_focus(self.paste_target)
        assert self.focused is self.paste_target
        if os.environ.get("TOAD_TEST_REMOVE_CLIPBOARD_TOOL"):
            os.environ["PATH"] = str(self.project_dir / "no-tools")
        self._bindings.bind("ctrl+y", "copy_payload", show=False, priority=True)
        self.set_interval(0.05, self.record_paste)
        (self.project_dir / "ready.json").write_text(
            json.dumps(
                {
                    "transport": self.clipboard_transport.declared_name,
                    "installed": toad.__file__,
                    "focused": type(self.focused).__name__,
                }
            )
        )

    def action_copy_payload(self) -> None:
        self.copy_to_clipboard(PAYLOAD)
        (self.project_dir / "copied.json").write_text(
            json.dumps(
                {
                    "transport": self.clipboard_transport.declared_name,
                    "complete_local_value": self.clipboard == PAYLOAD,
                    "length": len(self.clipboard),
                    "focused": type(self.focused).__name__,
                }
            )
        )
        self.paste_target.focus()

    def record_paste(self) -> None:
        if self.paste_target.text:
            (self.project_dir / "pasted.json").write_text(
                json.dumps(
                    {
                        "complete_prompt_value": self.paste_target.text == PAYLOAD,
                        "length": len(self.paste_target.text),
                    }
                )
            )
            self.exit()


if __name__ == "__main__":
    import sys

    CopyApp(project_dir=sys.argv[1], mode="store").run()
