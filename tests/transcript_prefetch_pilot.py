"""Lookahead is worker-owned data: bounded, shared, cancellable, never mounted."""

import asyncio
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage

from runtime_fixture import ToadApp
from toad.transcript_preparation import PageRequest, TranscriptPageBuffer
from toad.widgets.transcript_history import TranscriptHistory
from toad.work_preparation import PreparationRuntime


def cursor(offset):
    return TranscriptCursor("fixture", offset)


def page(before, after, *, text=None):
    return TranscriptPage((TranscriptEvent("assistant", text or f"Page {before}\n\n" + "- row\n" * 25),),
                          cursor(before), cursor(after), before > 0, after < 1000)


class Renderer:
    def __init__(self):
        self.threads = []

    async def submit(self, task):
        def execute():
            self.threads.append(threading.get_ident())
            return task.execute()
        return await asyncio.to_thread(execute)

    async def aclose(self):
        pass


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(.01)


async def model_checks():
    reads = []
    renderer = Renderer()
    runtime = PreparationRuntime(renderer, max_entries=16)

    async def load(*, before=None, after=None, through=None):
        reads.append((before, after, through))
        return page(before.offset - 10, before.offset) if before else page(after.offset, after.offset + 10)

    buffer = TranscriptPageBuffer(load, cursor(1000), runtime)
    await buffer.prefetch(cursor(500), cursor(510), lambda: True)
    assert len(reads) == 16 and len(runtime._ready) == 16
    assert all(identity != threading.get_ident() for identity in renderer.threads)
    expected = await buffer.get(PageRequest(before=cursor(500)))
    assert expected.page.before == cursor(490) and len(reads) == 16
    await buffer.prefetch(cursor(400), cursor(610), lambda: True)
    assert len(runtime._ready) <= runtime.max_entries and runtime.retained_bytes <= runtime.max_bytes

    # Two consumers share a blocked read. Cancellation keeps the underlying
    # reader alive and its result available for the remaining consumer.
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def delayed(**kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return page(100, 110)

    shared = TranscriptPageBuffer(delayed, cursor(1000), runtime)
    request = PageRequest(before=cursor(110))
    first = asyncio.create_task(shared.get(request))
    await entered.wait()
    second = asyncio.create_task(shared.get(request))
    first.cancel()
    try:
        await first
    except asyncio.CancelledError:
        pass
    assert calls == 1 and len(runtime._pending) == 1
    release.set()
    assert (await second).page.before == cursor(100) and calls == 1
    shared.close()
    assert all(key.scope is not shared.scope for key in runtime._ready)

    # A retiring view drains already-running IO but never retains late results.
    entered.clear()
    release.clear()
    retired = TranscriptPageBuffer(delayed, cursor(1000), runtime)
    waiter = asyncio.create_task(retired.get(request))
    await entered.wait()
    retired.close()
    release.set()
    try:
        await waiter
    except asyncio.CancelledError:
        pass
    assert all(key.scope is not retired.scope for key in runtime._ready) and not runtime._pending

    # Oversized nested tool inputs also count toward the cache's memory budget.
    async def huge(**kwargs):
        event = TranscriptEvent("tool_start", "", tool_call_id="large", tool_name="read",
                                raw_input={"payload": "x" * 10000})
        return TranscriptPage((event,), cursor(100), cursor(110), True, True)

    small_runtime = PreparationRuntime(renderer, max_bytes=1024)
    bounded = TranscriptPageBuffer(huge, cursor(1000), small_runtime)
    result = await bounded.get(request)
    assert result.retained_bytes > small_runtime.max_bytes and not small_runtime._ready
    await small_runtime.aclose()

    failures = 0

    async def duplicate(**kwargs):
        nonlocal failures
        failures += 1
        return page(110, 110)

    broken = TranscriptPageBuffer(duplicate, cursor(1000), runtime)
    for _ in range(5):
        await broken.prefetch(cursor(110), None, lambda: True)
    assert failures == 1, "Speculative no-progress reads must not loop"
    try:
        await broken.get(request)
    except ValueError:
        pass
    else:
        raise AssertionError("Foreground no-progress read must report its error")
    assert failures == 2
    await runtime.aclose()


async def mounted_checks():
    with tempfile.TemporaryDirectory(prefix="toad-prefetch-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        reads = []

        async def load(*, before=None, after=None, through=None):
            reads.append((before, after))
            return page(before.offset - 10, before.offset)

        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            initial = page(900, 1000)
            pager = TranscriptHistory(initial, load)
            with patch.object(TranscriptHistory, "_check_edges", lambda self: None):
                await view.contents.mount(pager)
                await until(lambda: pager._prefetched_edges is not None)
                await pilot.pause()
                assert len(reads) == 8 and len(pager.pages) == 1
                assert len(pager.pages[0].children) == len(pager.pages[0].fragments), "Warm pages mounted hidden widgets"
                assert view.displayed_transcript_cursor is None, "Lookahead advanced painted history"
                calls = len(reads)
                view.window.release_anchor()
                pager._request_page(True)
                await until(lambda: not pager._loading)
                await pilot.pause()
                assert pager.pages[0].page.before == cursor(890)
                assert (cursor(900), None) in reads and reads.count((cursor(900), None)) == 1
                assert len(reads) <= calls + 1, "Consuming a warm page replayed its source read"
                assert app._exception is None

                entered, release = asyncio.Event(), asyncio.Event()

                async def delayed(**kwargs):
                    entered.set()
                    await release.wait()
                    return page(800, 900)

                late = TranscriptHistory(initial, delayed)
                await view.contents.mount(late)
                await entered.wait()
                late._request_page(True)
                await asyncio.sleep(0)
                await app.new_session_screen(app.get_main_screen)
                release.set()
                await until(lambda: not late._loading)
                assert len(late.pages) == 1, "Late foreground result mounted into a hidden tab"
                assert late.window.history_anchor is None and not late.window.history_lock.locked()
        await asyncio.get_running_loop().shutdown_default_executor()


async def main():
    await model_checks()
    await mounted_checks()
    print("transcript lookahead: worker preparation, 16-page/byte bounds, shared reads, cancellation, stale retirement, no-progress and data-only warming OK")


if __name__ == "__main__":
    asyncio.run(main())
