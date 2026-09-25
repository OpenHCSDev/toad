"""Real Toad/LinuxDriver fixture for native_tab_terminal_check.py; no mocks."""

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from typing import ClassVar

from rich.color import ColorSystem

import toad
from toad.app import ToadApp
from toad.widgets.session_tabs import SessionsTabs, Underline


class NativeTabApp(ToadApp):
    CSS_PATH: ClassVar[list[Path]] = [
        Path(toad.__file__).parent / "toad.tcss",
        Path(toad.__file__).parent / "screens/comms.tcss",
    ]

    def on_ready(self):
        self.capture_root = Path(self.project_dir)
        self.control_buffer = b""
        self.control_fd = os.open(self.capture_root / "control", os.O_RDWR | os.O_NONBLOCK)
        asyncio.get_running_loop().add_reader(self.control_fd, self.receive_control)
        self.run_worker(self.prepare_tabs(), exit_on_error=True)

    async def prepare_tabs(self):
        self.preview_modes = [self.current_mode]
        self.session_tracker.update_session(self.current_mode, title="pr17-implementation", state="idle")
        details = await self.new_session_screen(self.get_main_screen)
        self.preview_modes.append(details.mode_name)
        self.session_tracker.update_session(details.mode_name, title="agent-comms-ux", state="idle")
        self.clear_notifications()
        await asyncio.sleep(.5)
        self.record_frame("ready")

    def record_frame(self, name):
        # No compositor lookup/full render: those masked the viewport-only bug.
        underline = self.screen.query_one(SessionsTabs).query_one(Underline)
        color = underline.get_component_rich_style("underline--bar").color
        (self.capture_root / f"{name}.json").write_text(json.dumps({
            "size": list(self.size), "mode": self.current_mode, "theme": self.theme,
            "rgb": list(color.downgrade(self.console._color_system or ColorSystem.TRUECOLOR).get_truecolor())
            if color is not None and color.triplet is not None else None,
        }))

    def receive_control(self):
        self.control_buffer += os.read(self.control_fd, 4096)
        while b"\n" in self.control_buffer:
            line, self.control_buffer = self.control_buffer.split(b"\n", 1)
            self.run_worker(self.act(json.loads(line)), exclusive=True, group="native-control")

    async def act(self, command):
        action = command["action"]
        if action == "exit":
            self.exit()
            return
        if action == "overflow":
            for name in ("mcp-pr77-trust-review", "pr48 adaptive compaction owner",
                         "mcp-goal-scope-consultant", "pr17-standby-liveness-owner",
                         "long-context-reviewer"):
                details = await self.new_session_screen(self.get_main_screen)
                self.preview_modes.append(details.mode_name)
                self.session_tracker.update_session(details.mode_name, title=name, state="idle")
        elif action == "select":
            await self.switch_mode(self.preview_modes[command["index"]])
        elif action == "theme":
            self.theme = command["theme"]
        elif action == "refresh":
            self.screen.refresh(repaint=True, layout=True)
        await asyncio.sleep(.5)
        self.record_frame(command["name"])


if __name__ == "__main__":
    root = Path(sys.argv[1])
    try:
        app = NativeTabApp(project_dir=str(root))
        app.run()
        if app._exception is not None:
            (root / "error.txt").write_text("".join(traceback.format_exception(app._exception)))
    except BaseException:
        (root / "error.txt").write_text(traceback.format_exc())
        raise
