"""The heap is frozen once, when the first history is shown, and never asked again."""

import gc
from types import SimpleNamespace
import unittest
from unittest import mock

from toad.app import HeapBeforeFreeze, HeapFrozen, ToadApp


class HeapFreeze(unittest.TestCase):
    def test_first_displayed_history_freezes_once(self):
        app = SimpleNamespace(heap=HeapBeforeFreeze())
        with mock.patch.object(gc, "freeze") as freeze, \
                mock.patch.object(gc, "get_freeze_count", side_effect=AssertionError("counts the frozen heap")):
            for _ in range(5):
                ToadApp.history_displayed(app)
        self.assertEqual(freeze.call_count, 1)
        self.assertIsInstance(app.heap, HeapFrozen)

    def test_application_start_does_not_freeze(self):
        self.assertNotIn("gc.freeze", open(ToadApp.on_mount.__code__.co_filename).read().split(
            "async def on_mount(self) -> None:")[1].split("\n    def ")[0])


if __name__ == "__main__":
    unittest.main()
