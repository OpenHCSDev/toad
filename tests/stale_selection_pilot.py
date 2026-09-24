"""A selection drag cannot target a retired diff widget from a stale hit map."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from textual import events
from textual.geometry import Offset
from textual.screen import Screen
from runtime_fixture import ToadApp
from toad.widgets.patch_diff import PatchDiffView, parse_patch


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-stale-selection-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            diff = PatchDiffView(parse_patch("--- file.py\n+++ file.py\n@@ -1 +1 @@\n-old\n+new\n"), split=False)
            await app.screen.conversation.post(diff)
            await pilot.pause()
            code = diff.query_one("DiffCode")
            await pilot.mouse_down(code, offset=(0, 0))
            x, y = code.region.x, code.region.y
            # Retire the selected node, but simulate the compositor returning
            # the previous frame's hit until its next layout has committed.
            await code.remove()
            assert code.parent is None
            with patch.object(Screen, "get_widget_and_offset_at", return_value=(code, Offset(0, 0))):
                app.screen._forward_event(events.MouseMove(None, x, y, 0, 1, 1, False, False, False))
            await pilot.mouse_up(offset=(x, y))
            await pilot.pause()
            assert app._exception is None
    print("selection: stale detached diff hit is ignored during drag rather than crashing")


if __name__ == "__main__":
    asyncio.run(main())
