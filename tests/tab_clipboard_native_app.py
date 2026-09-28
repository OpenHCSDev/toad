"""Installed Toad/LinuxDriver copy path driven by an actual terminal key."""

import json
from pathlib import Path
from typing import ClassVar

import toad
from toad.app import ToadApp

PAYLOAD = "Complete native clipboard café 界\n" * 2400


class CopyApp(ToadApp):
    CSS_PATH: ClassVar = [
        Path(toad.__file__).parent / "toad.tcss",
        Path(toad.__file__).parent / "screens/comms.tcss",
    ]

    def on_ready(self) -> None:
        self._bindings.bind("ctrl+y", "copy_payload", show=False, priority=True)
        (self.project_dir / "ready.json").write_text(
            json.dumps(
                {
                    "transport": self.clipboard_transport.declared_name,
                    "installed": toad.__file__,
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
                }
            )
        )
        self.exit()


if __name__ == "__main__":
    import sys

    CopyApp(project_dir=sys.argv[1], mode="store").run()
