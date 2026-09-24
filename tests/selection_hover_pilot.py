"""Dragging within one hovered text widget avoids repeated full hover restyles."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from textual import events
from textual.geometry import Offset

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-hover-drag-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            response = await conversation.post(AgentResponse("Select this phrase " * 25))
            await pilot.pause()
            text = response.query_one("MarkdownParagraph")
            await pilot.mouse_down(text, offset=(1, 0))
            screen = app.screen
            x, y = text.region.x + 3, text.region.y
            app.mouse_position = Offset(x, y)
            screen._forward_event(events.MouseMove(None, x, y, 2, 0, 1, False, False, False))
            assert app.mouse_over is not None
            previous_hover = app.hover_over
            with patch.object(app.stylesheet, "update_nodes", wraps=app.stylesheet.update_nodes) as restyle:
                for index in range(4, 10):
                    x = text.region.x + index
                    app.mouse_position = Offset(x, y)
                    screen._forward_event(events.MouseMove(None, x, y, 1, 0, 1, False, False, False))
                assert app.hover_over is previous_hover and restyle.call_count == 0
            await pilot.mouse_up(text, offset=(10, 0))
            assert screen.get_selected_text() and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("hover drag: same-widget pointer steps highlight text without stylesheet restyles")


if __name__ == "__main__":
    asyncio.run(main())
