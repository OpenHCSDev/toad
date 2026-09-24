"""Prepared style topology preserves native segments without UI span sweeps."""

import asyncio
from unittest.mock import patch

from textual.app import App
from textual.content import Content, Span
from textual.geometry import Offset, Region
from textual.selection import SELECT_ALL, Selection
from textual.style import Style
from textual.visual import RenderOptions
from textual_diff_view._diff_view import LineContent

from toad.widgets.patch_diff import (
    PatchDiffCode, PreparedDiffLine, _DiffPaint, _DiffRow, prepare_diff_line,
)


class RowApp(App):
    def compose(self):
        yield PatchDiffCode(LineContent([Content("dummy")], [""]))


async def main():
    lines = [
        Content(""), Content("plain"), Content("界é🙂 text"),
        Content("abcdef", [Span(0, 6, "bold"), Span(1, 4, "red"), Span(2, 5, "on blue 30%")]),
        Content("abcdef", [Span(0, 2, "bold"), Span(2, 4, "bold"), Span(4, 6, "")]),
        Content("abcdef", [Span(1, 3, Style.from_meta({"@click": "test", "offset": (9, 9)}))]),
        Content("abcdef", [Span(0, 6, "not-a-valid-style"), Span(3, 5, "underline")]),
    ]
    selections = [None, SELECT_ALL, Selection(Offset(1, 0), Offset(3, 0)),
                  Selection(None, Offset(2, 0)), Selection(Offset(2, 0), None),
                  Selection(Offset(-2, 0), Offset(-1, 0)), Selection(Offset(3, 0), Offset(3, 0))]
    app = RowApp()
    compared = 0
    async with app.run_test() as pilot:
        await pilot.pause()
        code = app.query_one(PatchDiffCode)
        unusual = Content("abc", [Span(-2, 8, "bold")])
        assert prepare_diff_line(unusual) is unusual
        for line in lines:
            prepared = prepare_diff_line(line)
            assert isinstance(prepared, PreparedDiffLine)
            for width in (0, 1, 4, 15):
                for base_style in (Style.null(), Style.parse("white on #123456")):
                    for line_style in ("", "on #345678 50%"):
                        visual = LineContent([prepared], [line_style])
                        for selection in selections:
                            options = RenderOptions(Style.parse, {}, selection, Style.parse("reverse on red 30%"))
                            paint = _DiffPaint(code, visual)
                            paint.width = width
                            paint.style = base_style
                            paint.options = options
                            expected = _DiffRow(visual, 0).render_strips(width, 1, base_style, options)[0]
                            if paint.link_style is not None:
                                expected = expected._apply_link_style(paint.link_style)
                            # Negative endpoints can fall outside very short
                            # rows; those unusual selections keep the native path.
                            from contextlib import nullcontext
                            negative = selection is not None and selection.start is not None and selection.start.x < 0
                            context = (nullcontext() if negative else
                                       patch.object(Content, "render", side_effect=AssertionError("UI span sweep")))
                            with context:
                                actual = paint.prepared_row(prepared, 0)
                            assert actual.cell_length == expected.cell_length
                            assert list(actual) == list(expected), (line, width, selection, list(actual), list(expected))
                            compared += 1
        # A synchronous paint must release its context even when a row fails.
        code.refresh()
        with patch.object(_DiffPaint, "row", side_effect=RuntimeError("row failed")):
            try:
                code.render_lines(Region(0, 0, code.size.width, 1))
            except RuntimeError as error:
                assert str(error) == "row failed"
            else:
                raise AssertionError("Row failure was not exercised")
        assert code._paint is None
    print(f"prepared diff rows: {compared} exact native segment/style/metadata cases; no UI span sweep; paint context released")


if __name__ == "__main__":
    asyncio.run(main())
