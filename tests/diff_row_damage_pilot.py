"""Native diff parity and viewport-bounded row work (no dependency patches)."""

import asyncio

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.content import Content
from textual.geometry import Offset, Region
from textual.selection import SELECT_ALL, Selection
from textual.style import Style
from textual.visual import RenderOptions, Visual
from textual_diff_view import DiffView
from textual_diff_view._diff_view import DiffCode, FoldedLineContent, LineAnnotations, LineContent

from toad.widgets.patch_diff import PatchDiffCode, PatchDiffView, _DiffRow, parse_patch


PATCH = ("--- a.py\n+++ a.py\n@@ -30,5 +30,6 @@\n"
         " \t界 é 🙂 https://example.com\n-old\n+new\n+extra\n \n "
         + "wide界" * 35 + "\n \n")


def equal_strip(actual, expected):
    assert actual.cell_length == expected.cell_length
    assert list(actual) == list(expected), (list(actual), list(expected))


def row_parity():
    lines = [Content("\t界é🙂".expandtabs()).stylize("bold red", 8, 10),
             Content(""), None, Content("abc"), Content("界" * 50), Content("")]
    visual = LineContent(lines, ["on #123456"] * len(lines), hatch_style=Style.parse("dim"))
    selections = [None, SELECT_ALL, Selection(Offset(9, 0), Offset(2, 4)),
                  Selection(None, Offset(1, 3)), Selection(Offset(1, 3), None)]
    for width in (1, 8, 30, 150):
        for selection in selections:
            options = RenderOptions(Style.parse, {}, selection, Style.parse("reverse bold"))
            expected = visual.render_strips(width, None, Style.parse("white"), options)
            for y, strip in enumerate(expected):
                actual = _DiffRow(visual, y).render_strips(width, 1, Style.parse("white"), options)[0]
                equal_strip(actual, strip)
                for x in (0, 1, 9, 21):
                    equal_strip(actual.crop(x, x + 17), strip.crop(x, x + 17))


class NativePatch(PatchDiffView):
    def compose(self):
        yield from DiffView.compose(self)


class DiffApp(App):
    def __init__(self, patch=PATCH):
        super().__init__()
        self.patch = patch

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield PatchDiffView(parse_patch(self.patch), id="fast", split=False)
            if self.patch == PATCH:
                yield NativePatch(parse_patch(self.patch), id="native", split=False)


async def mounted_parity():
    app = DiffApp()
    async with app.run_test(size=(85, 25)) as pilot:
        fast = app.query_one("#fast", PatchDiffView)
        native = app.query_one("#native", NativePatch)
        for theme in ("textual-dark", "textual-light", "ansi-dark", "ansi-light"):
            app.theme = theme
            for split, wrap in ((False, False), (True, False), (True, True), (False, True), (False, False)):
                fast.split = native.split = split
                fast.wrap = native.wrap = wrap
                for size in ((85, 25), (49, 19)):
                    await pilot.resize_terminal(*size)
                    await pilot.pause()
                    fast_codes = list(fast.query(DiffCode))
                    native_codes = list(native.query(DiffCode))
                    assert len(fast_codes) == len(native_codes) == (2 if split else 1)
                    assert all(isinstance(code, PatchDiffCode) for code in fast_codes)
                    for code, original in zip(fast_codes, native_codes):
                        assert code.size == original.size
                        assert isinstance(code.render(), FoldedLineContent if wrap else LineContent)
                        for selection in (None, SELECT_ALL, Selection(Offset(2, 0), Offset(3, 3))):
                            app.screen.selections = {code: selection, original: selection} if selection else {}
                            code.refresh()
                            original.refresh()
                            expected = Visual.to_strips(original, original._render(), original.size.width,
                                                        original.size.height, original.visual_style)
                            for y, strip in enumerate(expected):
                                equal_strip(code.render_line(y), strip)
                            crop = Region(3, 0, min(19, code.size.width - 3), min(4, code.size.height))
                            for actual, strip in zip(code.render_lines(crop), original.render_lines(crop)):
                                equal_strip(actual, strip)
                            if selection:
                                assert code.get_selection(selection) == original.get_selection(selection)
                                if not wrap and selection == SELECT_ALL:
                                    assert "\t" not in code.get_selection(selection)[0]
                                    assert "界" in code.get_selection(selection)[0]
                    for gutter, original in zip(fast.query(LineAnnotations), native.query(LineAnnotations)):
                        assert gutter.total_width == original.total_width
                        for y in range(len(gutter.numbers)):
                            equal_strip(gutter.render_line(y), original.render_line(y))
        gutter = next(iter(fast.query(LineAnnotations)))
        gutter.numbers = [Content("123456789")]
        assert gutter.total_width == 9, "Reactive replacement must invalidate width"
        # Unusual alignment deliberately retains the native whole-visual path.
        code = fast.query_one(DiffCode)
        code.styles.content_align = ("center", "middle")
        code.refresh()
        expected = Visual.to_strips(code, code._render(), code.size.width, code.size.height, code.visual_style)
        for y, strip in enumerate(expected):
            equal_strip(code.render_line(y), strip)
        assert app._exception is None


class CountedLines(list):
    reads = 0
    scans = 0

    def __getitem__(self, key):
        self.reads += 1
        return super().__getitem__(key)

    def __iter__(self):
        self.scans += 1
        return super().__iter__()


async def bounded_damage():
    count = 20000
    huge = f"--- a.py\n+++ a.py\n@@ -1,{count} +1,{count} @@\n-old\n+new\n" + " context\n" * (count - 1)
    app = DiffApp(huge)
    async with app.run_test(size=(85, 25)) as pilot:
        await pilot.pause()
        code = app.query_one(PatchDiffCode)
        visual = code.render()
        lines = visual.code_lines = CountedLines(visual.code_lines)
        # The first dirty row used to trigger Static's whole-hunk rebuild.
        for selection in (SELECT_ALL, None):
            app.screen.selections = {code: selection} if selection else {}
            code.refresh()
            lines.reads = lines.scans = 0
            code.render_line(10000)
            assert lines.reads == 1 and lines.scans == 0
        gutters = list(app.query(LineAnnotations))
        for gutter in gutters:
            # Equal-valued reactive assignments are normally elided. Install
            # the instrumented list explicitly, then run its width invalidator.
            gutter.set_reactive(LineAnnotations.numbers, CountedLines(gutter.numbers))
            gutter.watch_numbers()
            gutter.total_width  # The one allowed scan on replacement.
            gutter.numbers.scans = 0
        for start in (0, 10000, 19980):
            lines.reads = lines.scans = 0
            code.refresh()
            app.screen.selections = {code: Selection(Offset(2, start), Offset(4, start + 8))}
            strips = code.render_lines(Region(0, start, 30, 12))
            assert len(strips) == 12
            assert 0 < lines.reads <= 12 and lines.scans == 0, (lines.reads, lines.scans)
            for gutter in gutters:
                for y in range(start, start + 12):
                    gutter.render_line(y)
                assert gutter.numbers.scans == 0
        # Exercise actual compositor refresh and scrolling as well as crops.
        # Settle reactive replacements and the queued selection transitions
        # above before measuring an isolated damage frame.
        await pilot.pause()
        lines.reads = lines.scans = 0
        code.refresh()
        await pilot.pause()
        assert 0 < lines.reads <= 50 and lines.scans == 0, lines.reads
        for selection in (Selection(Offset(1, 2), Offset(3, 8)), None):
            lines.reads = lines.scans = 0
            app.screen.selections = {code: selection} if selection else {}
            await pilot.pause()
            assert 0 < lines.reads <= 50 and lines.scans == 0, (lines.reads, lines.scans)
        lines.reads = 0
        app.query_one(VerticalScroll).scroll_to(y=10000, animate=False)
        await pilot.pause()
        assert 0 < lines.reads <= 50 and lines.scans == 0, lines.reads
        print(f"20,000-line hunk: 12-row damage <=12 row reads; scrolled frame {lines.reads} reads; no scans")


async def main():
    row_parity()
    await mounted_parity()
    await bounded_damage()
    print("diff row parity: segments/metadata/styles, copy, clipping, resize, wrap, themes, gutters passed")


if __name__ == "__main__":
    asyncio.run(main())
