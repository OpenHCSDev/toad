"""The Textual side of qt_drive's `history_scroll_back`: #comms on the same bus, at a phone-like
size, scrolled back by wheel steps until about 300 earlier rows load.

    PYTHONPATH=src python tools/tui_scroll_back.py PROFILE OUTDIR PROJECT

Writes OUTDIR/scroll-back.txt: the idle loop, then per older page the time from the reader
reaching the top to its rows drawn, and the loop's lateness over the scroll-back (10 ms ticks,
the frame probe's measure), so the two frontends compare line for line.
"""

import asyncio
import sys
import time
from pathlib import Path

from agent_comms.projects.checkouts import Checkout
from textual import events

from toad.app import ToadApp
from toad.client.connection import RemoteCoreConnection
from toad.client.history_preparation import OLDER_END
from toad.constants import WELCOME
from toad.launch_binding import NoAgent
from toad.navigation_context import NavigationContext
from toad.navigation_target import channel_target
from toad.widgets.history_anchor import HistoryWindow

ROWS_WANTED, SECONDS = 300, 150


async def main(profile: Path, out: Path, project: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    results = (out / "scroll-back.txt").open("w", buffering=1)
    app = ToadApp(agent_binding=NoAgent(), project_dir=Checkout(project),
                  connection=RemoteCoreConnection.read(profile))
    async with app.run_test(size=(46, 44)) as pilot:
        async with asyncio.timeout(180):
            while app.selected_mode != WELCOME:
                await pilot.pause(0.1)
        await channel_target("#comms").open(NavigationContext(app, app.selected_mode, app.project_dir, "user"))
        await pilot.pause(4.0)
        window = app.screen.query(HistoryWindow).first()
        late: list[float] = []
        state = {"stop": False}

        async def ticker() -> None:
            last = time.perf_counter()
            while not state["stop"]:
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                late.append((now - last) * 1000 - 10)
                last = now

        def rows() -> int:
            return sum(len(history.fragments) for history in window.histories)

        def first_key():
            return next((history.fragments[0].key for history in window.histories if history.fragments), None)

        idle = asyncio.ensure_future(ticker())
        await asyncio.sleep(8)
        state["stop"] = True
        await idle
        busy = sum(max(0.0, value) for value in late) / 8000 * 100
        results.write(f"idle: rows={rows()} worst_stall_ms={max(late):.0f} loop_busy={busy:.0f}%\n")
        late.clear()
        state["stop"] = False
        tick = asyncio.ensure_future(ticker())
        start_rows, pages = rows(), []
        started = time.perf_counter()
        deadline = started + SECONDS
        def older_left() -> bool:
            return any(OLDER_END.visible_more(history) for history in window.histories)

        while (rows() - start_rows < ROWS_WANTED and time.perf_counter() < deadline
               and (older_left() or window.scroll_y > 0)):
            first, reached = first_key(), None
            while time.perf_counter() < deadline and first_key() == first:
                if window.scroll_y <= 0 and not older_left():
                    break  # the reader is at the start of the history
                # A wheel step over the history, as the terminal delivers one.
                window.post_message(events.MouseScrollUp(window, 20, 20, 0, -1, 0, False, False, False, 20, 20))
                if reached is None and window.scroll_y <= 0:
                    reached = time.perf_counter()
                await asyncio.sleep(0.016)
            if first_key() != first:
                await pilot.pause(0)
                waited = (time.perf_counter() - reached) * 1000 if reached else 0.0
                pages.append(waited)
                results.write(f"page {len(pages)} rows={rows()} visible_after_top_ms={waited:.0f}\n")
        state["stop"] = True
        await tick
        span = time.perf_counter() - started
        busy = sum(max(0.0, value) for value in late) / (span * 1000) * 100
        buckets = " ".join(f">={bound}:{sum(value >= bound for value in late)}" for bound in (16, 33, 50, 100, 200, 500))
        ordered = sorted(pages)
        results.write(f"scroll back: span={span:.0f}s pages={len(pages)} rows_loaded={rows() - start_rows} "
                      f"visible_after_top_ms_median={ordered[len(ordered) // 2] if ordered else 0:.0f} "
                      f"max={ordered[-1] if ordered else 0:.0f} worst_stall_ms={max(late):.0f} "
                      f"loop_busy={busy:.0f}% {buckets}\n")
    print((out / "scroll-back.txt").read_text(), flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
