"""Same-scene damaged-frame comparison for native vs viewport diff rendering."""

import asyncio
import statistics
import time
from unittest.mock import patch

from textual.containers import VerticalScroll
from textual.geometry import Offset
from textual.selection import Selection
from textual_diff_view._diff_view import DiffCode
from diff_row_damage_pilot import DiffApp
from toad.widgets.patch_diff import PatchDiffCode


class TimedDiff(DiffApp):
    pending = None

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if (self.pending is not None and not self.pending.done()
                and renderable is not None and not self._batch_count):
            self.pending.set_result(time.perf_counter())
        return result


async def main():
    count = 20000
    huge = f"--- a.py\n+++ a.py\n@@ -1,{count} +1,{count} @@\n-old\n+new\n" + " context\n" * (count - 1)
    app = TimedDiff(huge)
    row_renderer = PatchDiffCode.render_line
    samples = {"native": [], "viewport": []}
    async with app.run_test(size=(85, 25)) as pilot:
        await pilot.pause()
        code = app.query_one(PatchDiffCode)
        app.query_one(VerticalScroll).scroll_to(y=10000, animate=False, immediate=True)
        await pilot.pause()
        # Interleave on one mounted scene to avoid confusing startup or
        # different source data with a rendering improvement.
        for round_index in range(5):
            for name, renderer in (("native", DiffCode.render_line), ("viewport", row_renderer)):
                with patch.object(PatchDiffCode, "render_line", renderer):
                    app.pending = asyncio.get_running_loop().create_future()
                    started = time.perf_counter()
                    app.screen.selections = {code: Selection(
                        Offset(round_index, 10000), Offset(round_index + 2, 10008))}
                    code.refresh()
                    finished = await asyncio.wait_for(app.pending, 10)
                    samples[name].append((finished - started) * 1000)
                    app.pending = None
                    await pilot.pause()
    print({"hunk_rows": count, "boundary": "headless post-_display; not terminal presentation",
           "selection_damage": {name: {"median_ms": round(statistics.median(values), 2),
                                       "worst_ms": round(max(values), 2)}
                                for name, values in samples.items()}})


if __name__ == "__main__":
    asyncio.run(main())
