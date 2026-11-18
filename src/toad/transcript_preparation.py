"""A saved transcript's pages, read from its file and prepared as Textual's transcript fragments
in the render workers. The sources and prepared pages they fill are shared (client.prepared_pages)."""

from __future__ import annotations

import asyncio
import pickle
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from hashlib import sha256

from agent_comms.execution.transcript_sources import (
    AtFrontier,
    LatestPage,
    PageLimit,
    PagePosition,
    TranscriptCursor,
)
from agent_comms.nominal.field_codec import ContentExclude, FieldCodec
from agent_comms.transcript.transcripts import TranscriptPage

from toad.client.history_preparation import (
    NEWER_END,
    OLDER_END,
    PageRequest,
)
from toad.client.prepared_pages import (
    PreparedPageSource,
    PreparedTranscriptPage,
    SavedHistory,
    SourcePageWork,
    TranscriptNoProgress,
)
from toad.client.message_files import NO_PAGE_FILES, PageFiles
from toad.client.transcript_fragments import FragmentClasses, transcript_fragments
from toad.render_backend import ContentAddressedRenderTask
from toad.work_preparation import (
    PreparationRuntime,
    PreparedResult,
    RenderPreparation,
    ReusableStorage,
    WorkKey,
)


class TranscriptPages(ABC):
    """Where a saved transcript's pages are read, and the files each page's messages carry."""

    @abstractmethod
    async def get_transcript_page(
        self, *, position: PagePosition = LatestPage(), limit: PageLimit = AtFrontier(),
    ) -> TranscriptPage: ...

    @abstractmethod
    async def page_files(self, page: TranscriptPage, classes: FragmentClasses) -> PageFiles:
        """One read of the files every bus message on ``page`` carries."""


@dataclass(frozen=True)
class LoadedTranscriptPages(TranscriptPages):
    """Pages read by ``load`` with no file store beside them, so a page shows no files: an
    attached history's, whose files stay with the bus that recorded them."""

    load: Callable[..., Awaitable[TranscriptPage]]

    async def get_transcript_page(
        self, *, position: PagePosition = LatestPage(), limit: PageLimit = AtFrontier(),
    ) -> TranscriptPage:
        return await self.load(position=position, limit=limit)

    async def page_files(self, page: TranscriptPage, classes: FragmentClasses) -> PageFiles:
        return NO_PAGE_FILES


@dataclass(frozen=True)
class TranscriptPageRenderTask(ReusableStorage[PreparedTranscriptPage], ContentAddressedRenderTask[PreparedTranscriptPage]):
    page: TranscriptPage
    classes: FragmentClasses
    files: PageFiles

    def preparation_digest(self, work: RenderPreparation[PreparedTranscriptPage]) -> bytes:
        """Read marks and coordination activity cannot change prepared content; the files its
        messages carry do."""
        return sha256(pickle.dumps(
            (FieldCodec.project(self.page, ContentExclude), self.files), protocol=5)).digest()

    def result_size(self, result: PreparedTranscriptPage) -> int:
        return result.retained_bytes

    def execute(self) -> PreparedTranscriptPage:
        """Prepare and measure one whole page in the worker that owns its result."""
        fragments = transcript_fragments(
            self.page.events,
            resolve_sent=self.page.resolve_sent_messages,
            classes=self.classes,
            files=self.files,
        )
        return PreparedTranscriptPage.measured(self.page, fragments)

    async def prepared(self, runtime: PreparationRuntime) -> PreparedTranscriptPage:
        """Reuse immutable suppliers, never another read's page metadata."""
        prepared = await runtime.submit(RenderPreparation(self))
        return replace(prepared, page=self.page)


@dataclass(frozen=True)
class TranscriptPageWork(SourcePageWork[TranscriptCursor]):
    """Read one saved transcript page and prepare its fragments in the render workers."""

    classes: FragmentClasses

    async def execute(self, runtime: PreparationRuntime, key: WorkKey) -> PreparedResult[PreparedTranscriptPage]:
        request = self.request
        page = await request.end.load_page(self.loader.get_transcript_page, request.cursor, self.through)
        if not request.progressed(page):
            raise TranscriptNoProgress(request, self.through, page)
        files = await self.loader.page_files(page, self.classes)
        if self.scope.closed:
            raise asyncio.CancelledError
        prepared = await TranscriptPageRenderTask(page, self.classes, files).prepared(runtime)
        return await runtime.run_thread(self.finish_result, key, prepared)


class SavedTranscript(SavedHistory):
    """A saved transcript's pages, read from its file and prepared in the render workers."""

    work = TranscriptPageWork


class SavedSuffix(SavedTranscript):
    """The same saved pager, starting after a local entry's source boundary."""

    def __init__(self, loader, through, runtime, *, after: TranscriptCursor, fragments: FragmentClasses) -> None:
        super().__init__(loader, through, runtime, fragments=fragments)
        self.after = after

    async def _get(self, request: PageRequest) -> PreparedTranscriptPage:
        prepared = await super()._get(request)
        if prepared.page.before.within(self.after):
            prepared = await super()._get(PageRequest(NEWER_END, self.after))
        if prepared.page.before.same_position(self.after):
            prepared.page = replace(prepared.page, has_older=False)
        return prepared

    def replacement(self, through) -> SavedSuffix:
        return type(self)(self.loader, through, self.runtime, after=self.after, fragments=self.fragments)

    async def for_rebuild(self) -> PreparedPageSource:
        """Local widgets end with their view; the next view reads the whole saved source."""
        source = SavedTranscript(self.loader, self.through, self.runtime, fragments=self.fragments)
        prepared = await source.get(PageRequest(OLDER_END, self.through))
        source.park((prepared,))
        return source
