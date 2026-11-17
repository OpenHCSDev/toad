"""The toolkit-neutral surface `BoundView` reaches on its transcript-history child.

Textual's `TranscriptHistory` is a `Widget` built on `LineHistory` / `CommittedHistory`
/ `VerticalGroup` — the full scroll chassis. Qt's `QtConversationHistory` carries its
own paint path and is not a Textual widget. `BoundView` does not need either whole
widget; it uses a bounded set of hooks (conversation order, coverage, retire/restore,
input/outgoing coverage). Both widgets satisfy this protocol structurally, so the
same `BoundView` wraps either one without caring which backend painted it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    from toad.client.history_coverage import HistoryCoverage
    from toad.client.prepared_pages import PreparedPageSource
    from toad.core.events import InputStartedUpdate
    from toad.transcript_messages import PublishedSentMessage


@runtime_checkable
class TranscriptHistoryContract(Protocol):
    """What `BoundView` reads and calls on its transcript-history child; both
    Textual's `TranscriptHistory` and Qt's `QtConversationHistory` provide it."""

    conversation_order: int

    @property
    def state(self) -> "_HasCoverage": ...

    def covers_outgoing(self, message: "PublishedSentMessage") -> bool: ...

    def covers_input(self, started: "InputStartedUpdate") -> bool: ...

    def close(self) -> None: ...

    async def restore_source(self, source: "PreparedPageSource", current) -> None: ...


@runtime_checkable
class _HasCoverage(Protocol):
    @property
    def coverage(self) -> "HistoryCoverage": ...
