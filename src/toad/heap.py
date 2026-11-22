"""This process's heap, and when Python's cyclic collector walks all of it.

Measured 2026-11-22 (Python 3.14.8, a finger scroll back through a long thread, Qt):

- A full collection walks every tracked object that is not frozen, with every thread stopped:
  74 ms for 235,000 objects on a desktop, several times that on a phone.
- Python starts one when its old generation has grown by a quarter. Loading a page of history
  is the heap growing, so the stop landed while the reader was pulling history in: four of
  119 to 180 ms in one scroll back.
- The young and middle collections walk what was made since the last one: 0.1 and 1.2 ms.

So what lives as long as the process is frozen out of every walk (the first painted history,
`CollectedByPython`), Python's own full collection is then switched off, and the full
collection runs from here: once enough was made to be worth one, and the reader has been
still for `Heap.STILL_SECONDS`. What waits meanwhile is only garbage held in reference
cycles; everything else is freed where its last reference goes.

One per process, as the collector is: `HEAP`. Both frontends' applications and reader
windows tell it the same three things.
"""
from __future__ import annotations

import asyncio
import gc
from typing import ClassVar


class HeapSchedule:
    """Who starts a full collection, and when. Each answer is the schedule from then on."""

    def history_displayed(self, heap: Heap) -> HeapSchedule:
        return self

    def reader_moved(self, heap: Heap) -> HeapSchedule:
        return self

    def reader_still(self, heap: Heap) -> HeapSchedule:
        return self

    def collected(self, heap: Heap) -> HeapSchedule:
        return self


class CollectedByPython(HeapSchedule):
    """Nothing is frozen yet and Python collects as it likes; the first painted history
    freezes the heap.

    launch_root.started() froze the import graph at entry and freezes again at exit; this is
    the freeze in between: by then the modules, classes, type caches, the workspace and the
    first tab's history exist and mostly live as long as the process, so the collector stops
    scanning them (~70,000 objects took 12-18 ms, inside whatever callback was running).
    Anything alive then that later dies in a reference cycle is never collected; that is at
    most the heap at that moment (decision 2026-10-11, about 6-10 MB).
    """

    def history_displayed(self, heap: Heap) -> HeapSchedule:
        gc.freeze()
        young, middle, _full = gc.get_threshold()
        gc.set_threshold(young, middle, heap.BY_HAND)
        return CollectedWhenStill()


class CollectedWhenStill(HeapSchedule):
    """The heap is frozen and Python starts no full collection. Once one is due, the next
    painted history or the reader coming to rest starts the wait for it."""

    def history_displayed(self, heap: Heap) -> HeapSchedule:
        return self.reader_still(heap)

    def reader_still(self, heap: Heap) -> HeapSchedule:
        if not heap.due():
            return self
        return CollectionWaiting(asyncio.get_running_loop().call_later(heap.STILL_SECONDS, heap.collect))


class CollectionWaiting(CollectedWhenStill):
    """A full collection runs when the reader has stayed still; a reader who moves first puts
    it off until they next come to rest."""

    def __init__(self, timer: asyncio.TimerHandle) -> None:
        self.timer = timer

    def reader_still(self, heap: Heap) -> HeapSchedule:
        return self

    def reader_moved(self, heap: Heap) -> HeapSchedule:
        self.timer.cancel()
        return CollectedWhenStill()

    def collected(self, heap: Heap) -> HeapSchedule:
        return CollectedWhenStill()


class Heap:
    """The process's heap: frozen once, then fully collected only while the reader is still."""

    DUE_AFTER: ClassVar[int] = 10
    """Middle collections since the last full one that make a full one worth running: Python's
    own count (`gc.get_count()[2]`), which rises once for about 24,000 objects made and kept."""

    STILL_SECONDS: ClassVar[float] = 1.0
    """How long the reader has stayed at rest when the full collection runs."""

    BY_HAND: ClassVar[int] = 1 << 30
    """A third threshold Python's count never reaches: full collections start from here."""

    def __init__(self) -> None:
        self.schedule: HeapSchedule = CollectedByPython()
        self.full_collections = 0

    def workspace_restored(self) -> None:
        """The application started and its tabs are back. What is alive now (modules, classes,
        declared families, the restored tabs) lives as long as the process: one collection,
        then everything left is frozen out of later ones, which walk only what the run makes
        after it. A full collection otherwise walked all of it with the UI thread stopped:
        0.5 s in the middle of a scroll and 1.3 s at startup on a phone's speed."""
        gc.collect()
        gc.freeze()

    def history_displayed(self) -> None:
        """A view's history was painted, in either frontend."""
        self.schedule = self.schedule.history_displayed(self)

    def reader_moved(self) -> None:
        """A reader's window moved under input (`DirectionalPreparation._moved`)."""
        self.schedule = self.schedule.reader_moved(self)

    def reader_still(self) -> None:
        """A reader's travel ended (`DirectionalPreparation.settle`)."""
        self.schedule = self.schedule.reader_still(self)

    def due(self) -> bool:
        return gc.get_count()[2] >= self.DUE_AFTER

    def collect(self) -> None:
        """A full collection now: the wait ended with the reader still, or the application
        was put away (Android's suspend gives memory back)."""
        gc.collect()
        self.full_collections += 1
        self.schedule = self.schedule.collected(self)


HEAP = Heap()
