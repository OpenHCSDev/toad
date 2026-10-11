"""Textual-facing: ToadApp, the Textual application, freezes the heap once when the first history is shown and not at mount."""

from types import SimpleNamespace
from unittest import mock
import gc

from toad.app import HeapBeforeFreeze, HeapFrozen, ToadApp


def test_first_displayed_history_freezes_once():
    app = SimpleNamespace(heap=HeapBeforeFreeze())
    with mock.patch.object(gc, "freeze") as freeze, \
            mock.patch.object(gc, "get_freeze_count", side_effect=AssertionError("counts the frozen heap")):
        for _ in range(5):
            ToadApp.history_displayed(app)
    assert freeze.call_count == 1
    assert isinstance(app.heap, HeapFrozen)
