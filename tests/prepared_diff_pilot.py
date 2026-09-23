"""Process-prepared patches retain native colors, offsets, layouts and copying."""

import asyncio
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection
from textual_diff_view import DiffView
from textual_diff_view._diff_view import DiffCode

from toad.render_processes import RenderProcessPool
from toad.widgets.patch_diff import PatchDiffView, parse_patch, prepare_patch


PATCHES = [
    "--- a.py\n+++ a.py\n@@ -30,5 +30,6 @@\n"
    " \t界 é 🙂 https://example.com\n-old\n+new\n+extra\n \n " + "wide界" * 35 + "\n \n",
    "--- source.py\n+++ source.py\n@@ -1000000,3 +1000000,3 @@\n"
    " \t# 界 é 🙂\n-old = 123\n+new = 456\n \n",
]


class DiffApp(App):
    def __init__(self, source):
        self.source = source
        super().__init__()

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield PatchDiffView(parse_patch(self.source), id="prepared", split=False)
            yield PatchDiffView(parse_patch(self.source), id="reference", split=False)


async def main():
    RenderProcessPool.prepare_spawn()
    pool = RenderProcessPool()
    try:
        for source in PATCHES:
            app = DiffApp(source)
            async with app.run_test(size=(90, 30)) as pilot:
                prepared = app.query_one("#prepared", PatchDiffView)
                reference = app.query_one("#reference", PatchDiffView)
                for theme in ("textual-dark", "textual-light", "ansi-dark", "ansi-light"):
                    app.theme = theme
                    await pilot.pause()
                    # The native reference has settled. A worker must import
                    # its own unpatched highlighter, rather than run on this loop.
                    with patch.object(DiffView, "highlight", side_effect=AssertionError("UI-loop syntax highlight")):
                        data = await pool.run(prepare_patch, source, app.current_theme.ansi, app.current_theme.dark)
                    assert data.patch == parse_patch(source)
                    prepared._prepared = data
                    prepared._highlighted_code_lines = None
                    prepared.refresh(recompose=True)
                    for split, wrap in ((False, False), (True, False), (True, True), (False, True)):
                        prepared.split = reference.split = split
                        prepared.wrap = reference.wrap = wrap
                        for size in ((90, 30), (49, 19)):
                            await pilot.resize_terminal(*size)
                            await pilot.pause()
                            left, right = prepared.highlighted_code_lines, reference.highlighted_code_lines
                            for actual, expected in zip(left, right):
                                assert actual.positions.keys() == expected.positions.keys()
                                for index in actual.positions:
                                    assert actual[index].plain == expected[index].plain
                                    assert actual[index].spans == expected[index].spans
                            codes = list(prepared.query(DiffCode))
                            originals = list(reference.query(DiffCode))
                            assert len(codes) == len(originals) == (2 if split else 1)
                            for code, original in zip(codes, originals):
                                assert code.size == original.size
                                for selection in (None, SELECT_ALL, Selection(Offset(1, 0), Offset(5, 2))):
                                    app.screen.selections = ({code: selection, original: selection}
                                                             if selection is not None else {})
                                    code.refresh()
                                    original.refresh()
                                    for y in range(code.size.height):
                                        actual, expected = code.render_line(y), original.render_line(y)
                                        assert actual.cell_length == expected.cell_length
                                        assert list(actual) == list(expected)
                                    if selection is not None:
                                        assert code.get_selection(selection) == original.get_selection(selection)
                assert app._exception is None
        fallback = await pool.run(prepare_patch, "not a valid unified patch\n", False, True)
        assert fallback.patch is None and fallback.fallback.plain == "not a valid unified patch\n"
    finally:
        await pool.aclose()
    print("prepared diff: process-only highlighting; native spans/segments/copy across themes, wrapping, Unicode and sparse hunks")


if __name__ == "__main__":
    asyncio.run(main())
