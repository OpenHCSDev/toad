"""Busy-count paint must preserve a settled transcript's layout and scroll."""

import asyncio
from pathlib import Path
from unittest.mock import patch
from math import ceil
from time import monotonic

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static
from textual.screen import UPDATE_PERIOD

from toad.widgets.throbber import Throbber


class Probe(App):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"
    CSS = "Static.record { height: 1; }"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="history"):
            for index in range(2000):
                yield Static(f"Saved record {index}", classes="record")
            yield Throbber(id="throbber", refresh_interval=UPDATE_PERIOD * 2)


async def main():
    app = Probe()
    async with app.run_test(size=(100, 35)) as pilot:
        history = app.query_one("#history", VerticalScroll)
        indicator = app.query_one(Throbber)
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
        timer = None
        ticks = []
        with (
            patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange,
            patch.object(indicator, "automatic_refresh", wraps=indicator.automatic_refresh) as tick,
            patch.object(indicator, "refresh", wraps=indicator.refresh) as refresh,
        ):
            for count in (0, 1, 2, 1, 0):
                indicator.busy = count > 0
                await pilot.pause(0.2)
                assert geometry() == baseline, (count, geometry(), baseline)
                assert arrange.call_count == 0, (count, arrange.call_args_list)
                assert not any(call.kwargs.get("layout") for call in refresh.call_args_list)
                painted = "".join(strip.text for strip in indicator.render_lines(indicator.size.region))
                assert ("━" in painted) == (count > 0), (count, painted)
                assert indicator.busy == (count > 0)
                if count:
                    assert indicator.auto_refresh == indicator.refresh_interval == UPDATE_PERIOD * 2
                    assert indicator._auto_refresh_timer is not None
                    if timer is None:
                        timer = indicator._auto_refresh_timer
                    else:
                        assert indicator._auto_refresh_timer is timer, "Nested busy count restarted timer"
                else:
                    assert not painted.strip(), painted
                    assert indicator.auto_refresh is None
                    assert indicator._auto_refresh_timer is None
                before = tick.call_count
                started = monotonic()
                await pilot.pause(0.3)
                delta = tick.call_count - before
                ticks.append(delta)
                upper = ceil((monotonic() - started) / indicator.refresh_interval) + 2
                assert (1 <= delta <= upper if count else delta == 0), (count, delta)
            assert arrange.call_count == 0
            assert geometry() == baseline

    print(f"2000 rows; busy 0→1→2→1→0: stable geometry/scroll; ticks={ticks}")



if __name__ == "__main__":
    asyncio.run(main())
