"""Prepared code rows match native Label strips, metadata and offscreen copy."""

import asyncio

import os
import tempfile
from pathlib import Path
from importlib.resources import files
from runtime_fixture import ToadApp
from textual.content import Content
from textual.geometry import Offset, Size
from textual.selection import SELECT_ALL, Selection
from textual.widgets import Label
from textual.containers import Vertical

from toad.widgets.prepared_markdown import PreparedCodeLabel


CODE = Content("first\n\n\t界 é 🙂\n".expandtabs() + "wide界" * 30 + "\nlast")
CODE = CODE.stylize("bold red", 0, 4).stylize("italic blue", 7, 16)


class RowApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")
    CSS = "Label { height: auto; padding: 1 2; background: #112233; }"



async def main():
    root = Path(tempfile.mkdtemp(prefix="md-rows-"))
    os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                      XDG_CONFIG_HOME=str(root / "config"),
                      XDG_STATE_HOME=str(root / "state"),
                      XDG_DATA_HOME=str(root / "data"))
    app = RowApp(project_dir=str(root))
    async with app.run_test(size=(90, 35)) as pilot:
        await app.selected_session.wait_content_ready()
        await app.screen.mount(Vertical(
            PreparedCodeLabel(CODE, id="fast"), Label(CODE, id="native")))
        fast = app.screen.query_one("#fast", PreparedCodeLabel)
        native = app.screen.query_one("#native", Label)
        for width in (35, 200):
            for wrap in ("wrap", "nowrap"):
                fast.styles.width = native.styles.width = width
                fast.styles.text_wrap = native.styles.text_wrap = wrap
                await pilot.pause()
                await asyncio.wait_for(fast.wait_ready(), 20)
                await pilot.pause()
                assert fast.size == native.size, (width, wrap, fast.size, native.size, fast.content)
                for selection in (None, SELECT_ALL, Selection(Offset(1, 1), Offset(5, 4)),
                                  Selection(None, Offset(1, 2))):
                    app.screen.selections = ({fast: selection, native: selection}
                                             if selection is not None else {})
                    fast.refresh()
                    native.refresh()
                    fast.selection_updated(selection)
                    await asyncio.wait_for(fast.wait_ready(), 20)
                    for y in range(fast.size.height):
                        actual, expected = fast.render_line(y), native.render_line(y)
                        assert actual.cell_length == expected.cell_length, (width, wrap, y, fast.size, actual.cell_length, expected.cell_length, actual.text, expected.text)
                        assert list(actual) == list(expected), (width, wrap, y, list(actual), list(expected))
                    if selection is not None:
                        assert fast.get_selection(selection) == native.get_selection(selection)
        # Requests for one deep visible row must not format an entire code block.
        content = Content("\n".join(f"line {index}" for index in range(10000)))
        fast.update(content)
        fast.styles.width = 80
        fast.styles.text_wrap = "nowrap"
        await pilot.pause()
        await asyncio.wait_for(fast.wait_ready(), 20)
        assert "line 9998" in fast.render_line(9998).text
        assert fast.get_selection(SELECT_ALL)[0] == content.plain
        # Tabs can expand beyond raw cell width; keep native measurement until
        # the prepared source has actually normalized them.
        tabs = Content("\tlong-word\n\tsecond")
        fast.update(tabs)
        for width in (4, 12, 30):
            fast.styles.width = width + fast.styles.gutter.width
            await pilot.pause()
            await asyncio.wait_for(fast.wait_ready(), 20)
            assert fast.get_content_height(Size(width, 0), Size(90, 35), width) == tabs.get_height(fast.styles.get_rules(), width)
    print("Markdown rows: exact native strips/metadata/copy, padding, Unicode, worker wrapping and 10K-line addressing")


if __name__ == "__main__":
    asyncio.run(main())
