"""Typed, bounded channel-history reads, independent of widget publication."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.message_page import MessagePage
from agent_comms.presentation import WireRevision


class HistoryKind(str, Enum):
    CHANNEL = "channel"
    DIRECT = "dm"
    ALL = "irc"


def display_identity(kind: HistoryKind, page: MessagePage) -> tuple | None:
    """The inclusion basis, excluding read markers and changing bus cursors."""
    if page.historical_display is not None:
        displayed = page.historical_display.displayed
        return ("historical", displayed.viewer, displayed.viewer_created_at, page.history_revision)
    if kind is HistoryKind.DIRECT:
        basis = page.display_basis
        if basis is None:
            return None
        return (
            basis.root_identity, basis.bus_identity, basis.worktree, basis.requested_peer,
            basis.viewer, basis.viewer_created_at, basis.viewer_names,
            basis.peer, basis.peer_created_at, basis.peer_names, page.history_revision,
        )
    scope = page.display_scope
    if scope is None or scope.displayed is None:
        return None
    displayed = scope.displayed
    return (
        displayed.viewer, displayed.viewer_created_at, displayed.bus_identity,
        scope.channel, scope.targets, scope.any_mode,
        scope.participant_names if scope.any_mode else frozenset(), page.history_revision,
    )


@dataclass(frozen=True)
class HistoryReadRequest:
    comms: Comms
    kind: HistoryKind
    target: str
    project: Path
    initialized: bool
    after: int
    follow_tail: bool
    known_revision: WireRevision | None
    initial_limit: int
    page_limit: int
    max_bytes: int
    known_display: tuple | None = None

    def page(self, *, after: int | None = None, limit: int) -> MessagePage:
        if self.kind is HistoryKind.ALL:
            return self.comms.views.channel_display_page(
                self.target, worktree=str(self.project), after=after,
                limit=limit, max_bytes=self.max_bytes,
            )
        if self.kind is HistoryKind.DIRECT:
            return self.comms.views.dm_display_page(
                self.target, worktree=str(self.project), after=after,
                limit=limit, max_bytes=self.max_bytes,
            )
        return self.comms.views.channel_display_page(
            self.target, worktree=str(self.project), after=after,
            limit=limit, max_bytes=self.max_bytes,
        )

    def read(self) -> HistoryReadResult:
        """Perform all revision/watermark/page I/O on the reader thread."""
        revision = self.comms.views.revision()
        if self.initialized and revision == self.known_revision:
            return HistoryReadResult(self, revision, self.after, None, False)
        high_water = self.comms.bus.log.latest_sequence()
        if not self.initialized:
            return HistoryReadResult(self, revision, high_water, self.page(limit=self.initial_limit), False)
        if high_water <= self.after:
            if (
                self.known_display is not None
                and self.known_revision is not None
                and revision.files != self.known_revision.files
            ):
                probe = self.page(limit=1)
                if display_identity(self.kind, probe) != self.known_display:
                    return HistoryReadResult(
                        self, revision, high_water, self.page(limit=self.initial_limit), True
                    )
            return HistoryReadResult(self, revision, high_water, None, False)
        page = self.page(after=self.after, limit=self.page_limit)
        if (
            self.known_display is not None
            and display_identity(self.kind, page) != self.known_display
        ):
            return HistoryReadResult(
                self, revision, high_water, self.page(limit=self.initial_limit), True
            )
        replace_tail = bool(page.messages and page.has_newer and self.follow_tail)
        if replace_tail:
            page = self.page(limit=self.initial_limit)
        return HistoryReadResult(self, revision, high_water, page, replace_tail)


@dataclass(frozen=True)
class HistoryReadResult:
    request: HistoryReadRequest
    revision: WireRevision
    high_water: int
    page: MessagePage | None
    replace_tail: bool


class ChannelHistoryReader:
    """Own in-flight visible history reads until their actual I/O completes."""

    def __init__(self) -> None:
        self._pending: set[asyncio.Task[HistoryReadResult]] = set()
        self._closed = False

    async def read(self, request: HistoryReadRequest) -> HistoryReadResult:
        if self._closed:
            raise RuntimeError("Channel history reader is closed")
        task = asyncio.create_task(asyncio.to_thread(request.read), name="channel-history-read")
        self._pending.add(task)

        def finished(completed: asyncio.Task[HistoryReadResult]) -> None:
            self._pending.discard(completed)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
        await asyncio.wait((task,))
        return task.result()

    async def aclose(self) -> None:
        self._closed = True
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
