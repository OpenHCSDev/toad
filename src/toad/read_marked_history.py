"""A line history whose visible messages can be acknowledged."""
from abc import abstractmethod

from toad.transcript_preparation import ReplaceablePageSource
from toad.transcript_source_preparation import HistorySourceSnapshot
from toad.widgets.transcript_history import LineHistory


class ReadMarkedHistory(LineHistory):
    """Read-mark publication shares the existing line-history lifetime."""

    page_source: ReplaceablePageSource

    @property
    @abstractmethod
    def undrawn(self) -> bool: ...

    @abstractmethod
    async def source_is_current(self, snapshot: HistorySourceSnapshot) -> bool: ...

    @abstractmethod
    async def _mark_read(self, snapshot: HistorySourceSnapshot) -> None: ...
