"""Repeated animation frames reuse color tables with exact native segment parity."""

import asyncio
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.color import Color
from textual.style import Style
from textual.visual import RenderOptions
from toad.widgets.throbber import Throbber, ThrobberVisual


class Probe(App):
    CSS = "Throbber { height: 1; }"

    def compose(self) -> ComposeResult:
        yield Throbber()


async def main():
    app = Probe()
    async with app.run_test(size=(100, 30)) as pilot:
        indicator = app.query_one(Throbber)
        indicator.busy = True
        indicator.auto_refresh = None
        await pilot.pause()
        cached = ThrobberVisual.make_segments
        uncached = cached.__wrapped__
        cached.cache_clear()
        options = RenderOptions(lambda _: Style(), {})
        styles = [Style(background=Color.parse("#112233")), Style(background=Color.parse("#ddeeff"))]
        cases = [(width, style) for width in (0, 1, 17, 91) for style in styles]
        for _ in range(3):
            for width, style in cases:
                for clock in (.02, .42, .88):
                    indicator.refresh()
                    visual = indicator._render()
                    assert isinstance(visual, ThrobberVisual)
                    visual.get_time = lambda value=clock: value
                    actual = visual.render_strips(width, 1, style, options)
                    # The uncached native algorithm remains the parity control;
                    # reference acquisition must not evict the cache being tested.
                    with patch.object(ThrobberVisual, "make_segments", uncached):
                        expected = ThrobberVisual(get_time=lambda value=clock: value).render_strips(width, 1, style, options)
                    assert list(actual[0]) == list(expected[0])
                    assert actual[0].cell_length == width
        info = cached.cache_info()
        assert info.misses == len(cases), info
        assert info.hits == len(cases) * 8, info
        assert info.currsize == info.maxsize == 8
        indicator.busy = False
        assert indicator.render() == ""
        print({"frames": len(cases) * 9, "color_table_builds": info.misses,
               "cache_hits": info.hits, "exact_native_segments": True})
    cached.cache_clear()


if __name__ == "__main__":
    asyncio.run(main())
