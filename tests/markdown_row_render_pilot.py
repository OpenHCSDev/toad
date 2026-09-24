"""Prepared code rows match native Label strips, metadata and offscreen copy."""

import asyncio

from textual.app import App, ComposeResult
from textual.content import Content
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection
from textual.widgets import Label

from toad.widgets.prepared_markdown import PreparedCodeLabel


CODE = Content("first\n\n\t界 é 🙂\n".expandtabs() + "wide界" * 30 + "\nlast")
CODE = CODE.stylize("bold red", 0, 4).stylize("italic blue", 7, 16)


class RowApp(App):
    CSS = "Label { height: auto; padding: 1 2; background: #112233; }"

    def compose(self) -> ComposeResult:
        yield PreparedCodeLabel(CODE, tuple(CODE.split("\n", allow_blank=True)), id="fast")
        yield Label(CODE, id="native")


async def main():
    app = RowApp()
    async with app.run_test(size=(90, 35)) as pilot:
        fast = app.query_one("#fast", PreparedCodeLabel)
        native = app.query_one("#native", Label)
        for width in (35, 200):
            for wrap in ("wrap", "nowrap"):
                fast.styles.width = native.styles.width = width
                fast.styles.text_wrap = native.styles.text_wrap = wrap
                await pilot.pause()
                assert fast.size == native.size
                for selection in (None, SELECT_ALL, Selection(Offset(1, 1), Offset(5, 4)),
                                  Selection(None, Offset(1, 2))):
                    app.screen.selections = ({fast: selection, native: selection}
                                             if selection is not None else {})
                    fast.refresh()
                    native.refresh()
                    for y in range(fast.size.height):
                        actual, expected = fast.render_line(y), native.render_line(y)
                        assert actual.cell_length == expected.cell_length, (width, wrap, y, fast.size, actual.cell_length, expected.cell_length, actual.text, expected.text)
                        assert list(actual) == list(expected), (width, wrap, y, list(actual), list(expected))
                    if selection is not None:
                        assert fast.get_selection(selection) == native.get_selection(selection)
        # Requests for one deep visible row must not format an entire code block.
        content = Content("\n".join(f"line {index}" for index in range(10000)))
        fast.set_code(content, tuple(content.split("\n", allow_blank=True)))
        fast.styles.width = 80
        fast.styles.text_wrap = "nowrap"
        await pilot.pause()
        assert "line 9998" in fast.render_line(9998).text
        assert fast.get_selection(SELECT_ALL)[0] == content.plain
    print("Markdown rows: exact native strips/metadata/copy, padding, Unicode, wrapping fallback and 10K-line addressing")


if __name__ == "__main__":
    asyncio.run(main())
