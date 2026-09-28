"""One application-wide, bounded warm window working set."""

from collections import OrderedDict
from weakref import ref

from toad.widgets.history_anchor import HistoryWindow


class WindowPresentationPool:
    """Retain recently visited document bodies without one budget per tab."""

    DEFAULT_RECENT_WINDOWS = 3

    def __init__(self, *, max_windows: int = DEFAULT_RECENT_WINDOWS) -> None:
        if type(max_windows) is not int or max_windows < 0:
            raise ValueError("Warm window budget must be non-negative")
        self.max_windows = max_windows
        self._recent: OrderedDict[ref[HistoryWindow], None] = OrderedDict()

    def remember(self, window: HistoryWindow) -> None:
        for key in tuple(self._recent):
            if key() is None:
                self._recent.pop(key)
        key = ref(window)
        self._recent.pop(key, None)
        if self.max_windows:
            self._recent[key] = None
        while len(self._recent) > self.max_windows:
            displaced, _ = self._recent.popitem(last=False)
            if owner := displaced():
                owner.document_viewport.request()

    def protects(self, window: HistoryWindow) -> bool:
        return ref(window) in self._recent
