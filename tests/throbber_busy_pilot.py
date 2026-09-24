"""Busy-count paint must preserve a settled transcript's layout and scroll."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import var
from textual.widgets import Static

from toad.session_tracker import SidebarState
from toad.widgets.conversation import Conversation
from toad.widgets.side_bar import SideBar, SideBarToggle
from toad.widgets.throbber import Throbber


class History(VerticalScroll):
    # Exercise the production watcher without starting agents or IO owners.
    busy_count = var(0)
    watch_busy_count = Conversation.watch_busy_count


class Probe(App):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"
    CSS = "Static.record { height: 1; }"

    def compose(self) -> ComposeResult:
        yield SideBar(navigation=SidebarState())
        with History(id="history"):
            for index in range(2000):
                yield Static(f"Saved record {index}", classes="record")
            yield Throbber(id="throbber")


async def main():
    app = Probe()
    async with app.run_test(size=(100, 35)) as pilot:
        history = app.query_one(History)
        indicator = app.query_one(Throbber)
        sidebar = app.query_one(SideBar)
        toggle = app.query_one(SideBarToggle)
        history.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        compositor = app.screen._compositor

        def geometry():
            return (
                history.region, history.virtual_size, history.scroll_offset,
                history.max_scroll_y, indicator.region, toggle.region,
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
                history.busy_count = count
                await pilot.pause(0.2)
                assert geometry() == baseline, (count, geometry(), baseline)
                assert arrange.call_count == 0, (count, arrange.call_args_list)
                assert not any(call.kwargs.get("layout") for call in refresh.call_args_list)
                painted = "".join(strip.text for strip in indicator.render_lines(indicator.size.region))
                assert ("━" in painted) == (count > 0), (count, painted)
                assert indicator.busy == (count > 0)
                if count:
                    assert indicator.auto_refresh == 1 / 30
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
                await pilot.pause(0.3)
                delta = tick.call_count - before
                ticks.append(delta)
                assert (1 <= delta <= 16 if count else delta == 0), (count, delta)
            assert arrange.call_count == 0
            assert geometry() == baseline

        # The fixed gutter's glyph is paint-only in both orientations.
        with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
            for right in (False, True):
                toggle.right = right
                for collapsed in (True, False):
                    toggle.set_collapsed(collapsed)
                    await pilot.pause()
                    assert geometry() == baseline
                    assert arrange.call_count == 0
            toggle.right = False

            # Real sidebar geometry changes must still invoke full layout.
            expanded_width = sidebar.size.width
            sidebar.collapsed = True
            await pilot.pause()
            assert sidebar.size.width == 3
            assert history.size.width > baseline[0].width
            assert any(not call.kwargs.get("visible_only", False) for call in arrange.call_args_list)
            arrange.reset_mock()
            sidebar.collapsed = False
            await pilot.pause()
            assert sidebar.size.width == expanded_width
            assert geometry() == baseline
            assert arrange.call_count > 0
    print(f"2000 rows; busy 0→1→2→1→0: 0 arrangements, stable geometry/scroll; "
          f"ticks per 0.3s={ticks}; idle blank, busy painted; glyph-only 0 arrangements; "
          "sidebar collapse/expand retains layout")


if __name__ == "__main__":
    asyncio.run(main())
