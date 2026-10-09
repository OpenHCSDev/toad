"""Removal completion belongs to its nodes, not the application's input queue."""

import asyncio
import gc
from weakref import ref

import pytest

from textual.app import App
from textual.await_remove import AwaitRemove
from textual.events import Key
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input


async def test_pending_unmount_does_not_block_unrelated_native_input():
    entered, release, received = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class SlowUnmount(Widget):
        async def on_unmount(self):
            entered.set()
            await release.wait()

    class Prompt(Input):
        def watch_value(self, value):
            if value == "x":
                received.set()

    app = App()
    async with app.run_test() as pilot:
        prompt, retiring = Prompt(), SlowUnmount()
        await app.mount(prompt, retiring)
        prompt.focus()
        await pilot.pause()
        compositor = app.screen._compositor
        assert retiring in compositor.visible_widgets
        removal = retiring.remove()
        try:
            await asyncio.wait_for(entered.wait(), 1)
            # Retirement must precede delayed Unmount, including lazy map reads.
            assert not retiring.display
            assert retiring not in compositor.full_map
            assert retiring not in compositor.visible_widgets
            app._driver.send_message(Key("x", "x"))
            await asyncio.wait_for(received.wait(), .5)
            assert not release.is_set()
        finally:
            release.set()
            await removal


async def test_removal_publication_runs_once_for_all_waiters():
    release = asyncio.Event()
    source = asyncio.create_task(release.wait())
    publications = []
    removal = AwaitRemove([source], lambda: publications.append("removed"))
    release.set()
    await asyncio.gather(removal(), removal(), removal())
    await removal
    assert publications == ["removed"]


async def test_cancelling_a_waiter_does_not_cancel_node_teardown():
    release, entered = asyncio.Event(), asyncio.Event()
    source = asyncio.create_task(release.wait())
    removal = AwaitRemove([source])

    async def wait():
        entered.set()
        await removal

    waiter = asyncio.create_task(wait())
    await entered.wait()
    waiter.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not source.cancelled() and not source.done()
    finally:
        release.set()
        await asyncio.gather(source, return_exceptions=True)
    await removal


async def test_cancellation_during_async_publication_keeps_one_completion():
    entered, release = asyncio.Event(), asyncio.Event()
    published = []

    async def publish():
        entered.set()
        await release.wait()
        published.append("done")

    removal = AwaitRemove([], publish)
    waiter = asyncio.create_task(removal())
    await entered.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    await asyncio.gather(removal(), removal())
    assert published == ["done"]


async def test_publication_error_is_preserved_without_repeating_callback():
    attempts = []

    def publish():
        attempts.append("attempt")
        raise ValueError("removal publication failed")

    removal = AwaitRemove([], publish)
    for _ in range(2):
        with pytest.raises(ValueError, match="removal publication failed"):
            await removal
    assert attempts == ["attempt"]


async def test_widget_can_await_its_own_removal_without_waiting_on_itself():
    returned = asyncio.Event()

    class Retire(Message):
        pass

    class SelfRemoving(Widget):
        async def on_retire(self):
            await self.remove()
            returned.set()

    app = App()
    async with app.run_test() as pilot:
        node = SelfRemoving()
        await app.mount(node)
        node.post_message(Retire())
        await asyncio.wait_for(returned.wait(), 1)
        await pilot.pause()
        assert not node.is_attached


async def test_completed_removal_receipt_releases_retired_widgets():
    app = App()
    async with app.run_test() as pilot:
        node = Widget()
        await app.mount(node)
        reference = ref(node)
        removal = node.remove()
        await removal
        del node
        await pilot.pause()
        gc.collect()
        assert reference() is None, "Holding a completed receipt retained its removed widget"
        await removal
