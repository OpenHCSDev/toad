"""Textual-facing: the throbber's busy paint runs on the app's one animation clock and must preserve a settled transcript's layout and scroll.

The sweep runs on the app's one animation clock: one animation while busy,
none (and no timer) while idle.
"""

from importlib.resources import files
from unittest.mock import patch
from math import ceil
from time import monotonic

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static
from ui_theme.effects import ACTIVITY_SWEEP

from toad.textual_colours import ThemedApp
from toad.widgets.throbber import Throbber


class Probe(ThemedApp, App):
    CSS_PATH = files("toad").joinpath("toad.tcss")
    CSS = "Static.record { height: 1; }"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="history"):
            for index in range(2000):
                yield Static(f"Saved record {index}", classes="record")
            yield Throbber(id="throbber")


async def test_busy_paint_keeps_layout_and_scroll_and_uses_one_animation():
    app = Probe()
    async with app.run_test(size=(100, 35)) as pilot:
        history = app.query_one("#history", VerticalScroll)
        indicator = app.query_one(Throbber)
        clock = app.colours.clock
        history.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        compositor = app.screen._compositor

        def geometry():
            return (
                history.region, history.virtual_size, history.scroll_offset,
                history.max_scroll_y, indicator.region,
            )

        baseline = geometry()
        assert indicator.size.height == 1
        assert indicator in compositor.visible_widgets
        animation = None
        with (
            patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange,
            patch.object(indicator, "refresh", wraps=indicator.refresh) as refresh,
        ):
            # Paint changes must keep the fixed width and single row.
            revision = indicator._geometry_revision
            indicator.styles.background = "red"
            indicator.styles.opacity = 0.8
            await pilot.pause()
            assert indicator._geometry_revision == revision
            assert geometry() == baseline
            assert arrange.call_count == 0
            for busy in (False, True, True, False):
                indicator.busy = busy
                await pilot.pause(0.2)
                assert geometry() == baseline, (busy, geometry(), baseline)
                assert arrange.call_count == 0, (busy, arrange.call_args_list)
                assert not any(call.kwargs.get("layout") for call in refresh.call_args_list)
                painted = "".join(strip.text for strip in indicator.render_lines(indicator.size.region))
                assert ("━" in painted) == busy, (busy, painted)
                if busy:
                    assert clock.running == {indicator: indicator.animation}
                    assert indicator.animation.effect is ACTIVITY_SWEEP
                    assert app.colours._timer is not None
                    if animation is None:
                        animation = indicator.animation
                    else:
                        assert indicator.animation is animation, "Staying busy restarted the sweep"
                else:
                    assert not painted.strip(), painted
                    assert indicator.animation is None
                    assert not clock.running
                    assert app.colours._timer is None, "The clock kept a timer with nothing animating"
                before = refresh.call_count
                started = monotonic()
                await pilot.pause(0.3)
                delta = refresh.call_count - before
                upper = ceil((monotonic() - started) * ACTIVITY_SWEEP.frames_per_second) + 2
                assert (1 <= delta <= upper if busy else delta == 0), (busy, delta, upper)
            assert arrange.call_count == 0
            assert geometry() == baseline
