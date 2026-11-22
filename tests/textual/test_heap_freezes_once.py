"""Textual-facing: ToadApp, the Textual application, tells the process's heap of every history
shown, and the heap freezes once, at the first one and not at mount (`toad.heap`)."""

from types import SimpleNamespace
from unittest import mock
import gc

from toad import heap as heap_module
from toad.app import ToadApp
from toad.heap import CollectedWhenStill, Heap


def test_first_displayed_history_freezes_once(monkeypatch):
    heap = Heap()
    monkeypatch.setattr(heap_module, "HEAP", heap)
    monkeypatch.setattr("toad.client.application.HEAP", heap)
    monkeypatch.setattr(gc, "set_threshold", lambda *thresholds: None)
    monkeypatch.setattr(gc, "get_count", lambda: (0, 0, 0))
    with mock.patch.object(gc, "freeze") as freeze, \
            mock.patch.object(gc, "get_freeze_count", side_effect=AssertionError("counts the frozen heap")):
        for _ in range(5):
            ToadApp.history_displayed(SimpleNamespace())
    assert freeze.call_count == 1
    assert isinstance(heap.schedule, CollectedWhenStill)
