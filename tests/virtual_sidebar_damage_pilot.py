"""Retained sidebar rows match a full redraw without rebuilding row geometry."""

import asyncio
from contextlib import nullcontext
import statistics
import time
from types import MethodType
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.content import Content
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from toad.widgets.virtual_channel_list import VirtualChannelList


class DamageApp(App):
    CSS = "VirtualChannelList { width: 40; height: 24; }"
    pending = None

    def compose(self) -> ComposeResult:
        yield VirtualChannelList()

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if (self.pending is not None and not self.pending.done()
                and renderable is not None and not self._batch_count):
            self.pending.set_result(time.perf_counter())
        return result


async def main():
    app = DamageApp()
    async with app.run_test(size=(80, 30)) as pilot:
        listing = app.query_one(VirtualChannelList)
        listing.set_options([
            Option(Content(f"  worker-{i:04d}\n    Ready"), id=str(i))
            for i in range(1000)
        ])
        await pilot.pause()
        # Rendered stripes, hit-test metadata, geometry and row identities must
        # all survive a fixed-height content change, including at scroll offset.
        listing.scroll_to(y=180, animate=False, immediate=True)
        await pilot.pause()
        listing.render_lines(listing.size.region)
        retained_keys = [key for key in listing._option_render_cache.keys()
                         if key[0] is listing.get_option_at_index(92)]
        assert retained_keys
        retained_strips = [listing._option_render_cache[key] for key in retained_keys]
        geometry = tuple(listing._line_cache.lines)
        with patch.object(listing._line_cache, "clear", wraps=listing._line_cache.clear) as clear:
            listing.replace_option_prompt("90", Content("  (7) ✓ 界界界\n    Working on a very long status"))
            await pilot.pause()
            assert clear.call_count == 0, "Text update rebuilt all row positions"
        assert tuple(listing._line_cache.lines) == geometry
        for key, strips in zip(retained_keys, retained_strips):
            assert listing._option_render_cache[key] is strips
        before = [tuple(strip) for strip in listing.render_lines(listing.size.region)]
        listing._clear_caches()
        after = [tuple(strip) for strip in listing.render_lines(listing.size.region)]
        assert before == after, "Local damage differs from a full redraw"
        assert "Working" in listing.render_line(1).text
        assert listing.render_line(0)._segments[0].style.meta["option"] == 90

        listing.replace_option_prompt("90", Content("  worker\n    busy\n    extra line"))
        listing._update_lines()
        assert listing._line_cache.heights[90] == 3
        assert listing._line_cache.index_to_line[91] == 183
        listing.replace_option_prompt("90", Content("  worker\n    Ready"))
        await pilot.resize_terminal(60, 24)
        await pilot.pause()
        listing._update_lines()
        assert listing._line_cache.heights[90] == 2
        assert listing._line_cache.index_to_line[91] == 182

        results = {}
        for retained in (False, True):
            context = (nullcontext() if retained else patch.object(
                listing, "_replace_option_prompt",
                MethodType(OptionList._replace_option_prompt, listing)))
            timings = []
            with context:
                for tick in range(20):
                    await pilot.pause()
                    app.pending = asyncio.get_running_loop().create_future()
                    started = time.perf_counter()
                    for index in range(90, 98):
                        listing.replace_option_prompt(str(index), Content(
                            f"  worker-{index:04d}\n    Tick {tick} · {'retained' if retained else 'full'}"))
                    timings.append((await asyncio.wait_for(app.pending, 3) - started) * 1000)
                    app.pending = None
            results["retained" if retained else "full_invalidation"] = {
                "median_ms": round(statistics.median(timings), 2),
                "worst_ms": round(max(timings), 2),
            }
        print({"rows": listing.option_count, "updates_per_frame": 8,
               "boundary": "headless post-_display, not terminal presentation",
               "geometry_and_full_redraw_parity": True, "timings": results})


if __name__ == "__main__":
    asyncio.run(main())
