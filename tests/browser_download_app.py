"""Real Textual file-delivery child for the installed browser route pilot."""

import io
import shlex
import sys
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.widgets import Static

from toad.web_server import ToadWebServer

PAYLOAD = "Actual Textual driver delivery\n" * 5000


class FileDeliveryApp(App):
    BINDINGS: ClassVar = [("d", "deliver", "Download")]

    def compose(self) -> ComposeResult:
        yield Static("Real file delivery: press d")

    def action_deliver(self) -> None:
        self.deliver_text(
            io.StringIO(PAYLOAD),
            save_filename="browser-pilot.txt",
            mime_type="text/plain",
            encoding="utf-8",
        )


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        FileDeliveryApp().run()
    else:
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), "--child"])
        ToadWebServer(command, host="127.0.0.1", port=int(sys.argv[1])).serve()
