"""The process's heap is frozen at the first painted history; after that a full collection
runs only once one is due and the reader has stayed still (`toad.heap`)."""
from __future__ import annotations

import asyncio
import gc

import pytest

from toad import heap as heap_module
from toad.heap import CollectedByPython, CollectedWhenStill, CollectionWaiting, Heap


@pytest.fixture
def collector(monkeypatch):
    """Python's collector, heard and not run: what was called, and a count the test sets."""
    heard = {"freeze": 0, "collect": 0, "threshold": (2000, 10, 10), "count": (0, 0, 0)}
    monkeypatch.setattr(gc, "freeze", lambda: heard.__setitem__("freeze", heard["freeze"] + 1))
    monkeypatch.setattr(gc, "collect", lambda: heard.__setitem__("collect", heard["collect"] + 1))
    monkeypatch.setattr(gc, "get_threshold", lambda: heard["threshold"])
    monkeypatch.setattr(gc, "set_threshold", lambda *thresholds: heard.__setitem__("threshold", thresholds))
    monkeypatch.setattr(gc, "get_count", lambda: heard["count"])
    monkeypatch.setattr(Heap, "STILL_SECONDS", 0.01)
    return heard


def test_the_first_painted_history_freezes_the_heap_and_takes_full_collections_from_python(collector):
    heap = Heap()
    assert isinstance(heap.schedule, CollectedByPython)

    heap.history_displayed()
    heap.history_displayed()

    assert collector["freeze"] == 1
    assert collector["threshold"] == (2000, 10, Heap.BY_HAND)
    assert type(heap.schedule) is CollectedWhenStill


def test_a_due_collection_runs_once_the_reader_has_stayed_still(collector):
    async def scenario():
        heap = Heap()
        heap.history_displayed()
        collector["count"] = (0, 0, Heap.DUE_AFTER - 1)
        heap.reader_still()
        assert type(heap.schedule) is CollectedWhenStill, "nothing is due yet"

        collector["count"] = (0, 0, Heap.DUE_AFTER)
        heap.history_displayed()
        assert isinstance(heap.schedule, CollectionWaiting), "a page arrived and one is due"
        heap.reader_moved()
        assert type(heap.schedule) is CollectedWhenStill
        await asyncio.sleep(0.03)
        assert collector["collect"] == 0, "the reader moved: the collection was put off"

        heap.reader_still()
        heap.reader_still()
        await asyncio.sleep(0.03)
        assert collector["collect"] == 1
        assert heap.full_collections == 1
        assert type(heap.schedule) is CollectedWhenStill

    asyncio.run(scenario())


def test_both_frontends_and_the_shared_reader_tell_the_one_heap():
    """Qt's thread view did not until 2026-11-22: its heap was never frozen after startup."""
    import inspect

    from toad.client.application import ClientApplication
    from toad.client.history_pager import DirectionalPreparation
    from toad.qt.thread_view import QtThreadView
    from toad.widgets.conversation import Conversation

    from toad.client.view_binding_protocols import BoundViewHost

    # One sequence, the shared host's: neither frontend's view can leave the step out.
    for view in (QtThreadView, Conversation):
        assert view.history_painted is BoundViewHost.history_painted, view
    assert "self.app.history_displayed()" in inspect.getsource(BoundViewHost.history_painted)
    assert "HEAP.history_displayed()" in inspect.getsource(ClientApplication.history_displayed)
    assert "HEAP.reader_moved()" in inspect.getsource(DirectionalPreparation._moved)
    assert "HEAP.reader_still()" in inspect.getsource(DirectionalPreparation.settle)
    assert isinstance(heap_module.HEAP, Heap)
