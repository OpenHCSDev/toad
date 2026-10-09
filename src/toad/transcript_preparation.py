"""Bounded, data-only lookahead for one immutable transcript snapshot."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from weakref import ReferenceType, ref

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import TranscriptEvent

from toad.markdown_preparation import PreparedContentRange
from toad.widgets.transcript_fragments import TranscriptFragment
from toad.widgets.transcript_fragments import TranscriptRenderTask
from toad.widgets.message_filter import MessageCategory, keep_events
from toad.work_preparation import (
    PreparationRuntime,
    PreparedValue,
    RenderPreparation,
    PreparationScope,
    SerializedWork,
    ScopedWork,
    ThreadWork,
    WorkKey,
    WorkLane,
    retained_bytes,
)


@dataclass
class PreparedTranscriptPage(PreparedContentRange):
    page: TranscriptPage
    fragments: tuple[TranscriptFragment, ...]
    retained_bytes: int
    admission: tuple[int, int] | None = None
    batch_size: int = field(default=PreparedContentRange.BATCH, kw_only=True)
    admitted: tuple[TranscriptFragment, ...] = field(default=(), kw_only=True, compare=False, repr=False)

    # This page already owns prepared inputs. Markdown request acquisition is
    # a different lifetime; pages share only the admission implementation.
    input_ready = True

    def capture_admission(self) -> TranscriptPageAdmission:
        return TranscriptPageAdmission(ref(self), self.start, self.stop,
                                       self.resources(slice(self.start, self.stop)))

    def restore_admission(self, admission: TranscriptPageAdmission) -> None:
        if admission.page() is not self:
            return
        if len(admission.members) != admission.stop - admission.start:
            raise RuntimeError("Original transcript suppliers do not cover their admission")
        # This resource's inputs never change. The original bounded slots and
        # their acquisitions remain valid even after native demand moved to a
        # disjoint tail. A replacement page owns another source lifetime.
        self.select_admission(slice(admission.start, admission.stop))
        self.admitted = admission.members

    def publish_fragments(self, fragments):
        if fragments is not self.fragments:
            raise ValueError("Transcript input replacement requires a new prepared page")

    @property
    def retained_source_bytes(self):
        return self.retained_bytes

    # A page draws its admitted fragments as lines: admission moves a range,
    # it never mounts or removes native members.
    def compose(self, view):
        return ()

    async def extend(self, view, older: bool, current, *, prefix=()) -> bool:
        extension = self.extension_slice(older)
        selected = slice(extension.start if older else self.start,
                         self.stop if older else extension.stop)
        return await self.replace_range(view, self.fragments, selected, None, current)

    async def replace_range(self, view, fragments, selected, previous, current, *, prefix=(),
                            acquired=None, suppliers=None) -> bool:
        if not current():
            return False
        self.publish_fragments(fragments)
        self.select_admission(selected)
        self.retain_sources(view)
        view.admission_changed()
        return True

    def trim(self, view, count: int, *, older: bool) -> None:
        if older:
            self.start += count
        else:
            self.stop -= count
        self.retain_sources(view)
        view.admission_changed()

    def retain_sources(self, view) -> None:
        self.admitted = self.fragments[self.start:self.stop]

    def admit(self) -> PreparedTranscriptPage:
        """An independent view owns admission and resolved source acquisitions.

        The worker's immutable source/syntax remains reusable. Its stored page
        never acquires a frontend document or another projection's lifetime.
        """
        return replace(self, fragments=tuple(fragment.independent() for fragment in self.fragments),
                       admission=None, admitted=())


@dataclass(frozen=True, eq=False)
class TranscriptPageAdmission:
    """Reading demand holds this actual page's bounded source acquisitions.

    Reader intent retains its bounded original members, never the whole page.
    Native admission can move independently of these original source slots.
    Another page or projection never owns them merely because its backend
    interval happens to be equal.
    """

    page: ReferenceType[PreparedTranscriptPage] = field(repr=False)
    start: int
    stop: int
    members: tuple[TranscriptFragment, ...] = field(repr=False)

    def __eq__(self, other):
        if not isinstance(other, TranscriptPageAdmission):
            return NotImplemented
        return ((page := self.page()) is not None and page is other.page()
                and self.start == other.start and self.stop == other.stop)


@dataclass(frozen=True)
class PageRequest:
    before: TranscriptCursor | None = None
    after: TranscriptCursor | None = None


@dataclass(frozen=True)
class FilteredTranscriptBatch:
    fragments: tuple[TranscriptFragment, ...]
    stop: int


@dataclass(frozen=True)
class TranscriptFilterWork(ThreadWork[FilteredTranscriptBatch]):
    """Select the next bounded presentation batch off-loop from source data."""

    fragments: tuple[TranscriptFragment, ...]
    selected: frozenset[type[MessageCategory]]
    stop: int
    limit: int

    async def identity(self, runtime: PreparationRuntime) -> WorkKey:
        # This is a cursor operation, not a retained copy of the source history.
        return WorkKey(type(self), object())

    def prepare(self) -> FilteredTranscriptBatch:
        matches = []
        stop = self.stop
        if not self.selected:
            return FilteredTranscriptBatch((), 0)
        while stop and len(matches) < self.limit:
            stop -= 1
            fragment = self.fragments[stop]
            if keep_events(fragment.events, self.selected):
                matches.append(fragment)
        return FilteredTranscriptBatch(tuple(reversed(matches)), stop)


class PreparedPageSource(ABC):
    """One lifetime-owned source of prepared pages, independent of widget paging."""

    runtime: PreparationRuntime
    scope: PreparationScope
    through: TranscriptCursor
    loader: Callable[..., Awaitable[TranscriptPage]] | None

    def __init__(self) -> None:
        # Custody moves here when native membership is revoked. These are the
        # original admitted resources, not another cache of transport pages.
        self.admitted: tuple[PreparedTranscriptPage, ...] = ()
        self.projection_source: ProjectedTranscriptSource | None = None

    @property
    def retained_source_bytes(self) -> int:
        return sum(page.retained_bytes for page in self.admitted) + (
            self.projection_source.retained_source_bytes if self.projection_source is not None else 0
        )

    def measure_admission(self, pages: tuple[PreparedTranscriptPage, ...],
                          projection: ProjectedTranscriptSource | None = None,
                          admissions: tuple[TranscriptPageAdmission, ...] = (),
                          *, seen: set[int] | None = None) -> None:
        """Partition retained source custody in the existing preparation worker.

        A tool's mutable acquisition need not be a field of its immutable
        dataclass input. Include each owner's declared suppliers, rather than
        assuming a graph walk of transport fields reaches every document.
        Canonical and projected pages share immutable inputs; their independent
        acquisitions remain distinct while this one traversal counts sharing.
        """
        if seen is None:
            seen = set()
        for page in pages:
            readers = tuple(member for admission in admissions if admission.page() is page
                            for member in admission.members)
            page.retained_bytes = retained_bytes(
                (page.page, page.fragments, page.resolved_sources(),
                 readers, tuple(source for member in readers for source in member.resolved_sources())),
                seen=seen,
            )
        if projection is not None:
            projection.measure_admission(projection.admitted, projection.projection_source,
                                         admissions, seen=seen)

    def park(self, pages: tuple[PreparedTranscriptPage, ...],
             projection: ProjectedTranscriptSource | None = None) -> None:
        if self.closed:
            raise ValueError("Cannot retain a revoked transcript source")
        self.admitted, self.projection_source = pages, projection

    def release_admission(self) -> None:
        """Native acquisition takes these same resources, not materialized copies."""
        self.admitted, self.projection_source = (), None

    @property
    def closed(self) -> bool:
        return self.scope.closed

    @abstractmethod
    async def get(self, request: PageRequest) -> PreparedTranscriptPage:
        pass

    @abstractmethod
    def prefetch(
        self, before: TranscriptCursor | None, after: TranscriptCursor | None,
        keep_going: Callable[[], bool], *, rounds: int = 1,
    ) -> AsyncIterator[PreparedTranscriptPage]:
        pass

    def close(self) -> None:
        self.runtime.discard_scope(self.scope)
        if self.projection_source is not None:
            self.projection_source.close()
        self.release_admission()


class TranscriptPageProjection(ABC):
    @abstractmethod
    async def project(self, page: PreparedTranscriptPage, runtime: PreparationRuntime) -> PreparedTranscriptPage:
        pass


@dataclass(frozen=True)
class CategoryProjection(TranscriptPageProjection):
    selected: frozenset[type[MessageCategory]]

    async def project(self, page: PreparedTranscriptPage, runtime: PreparationRuntime) -> PreparedTranscriptPage:
        # Project one source page on the model lane. Widget admission is owned
        # separately by the same bounded pager used for unfiltered history.
        matches = await runtime.submit(TranscriptFilterWork(
            page.fragments, self.selected, len(page.fragments), len(page.fragments),
        ))
        return replace(page, fragments=tuple(fragment.independent() for fragment in matches.fragments),
                       admission=None, admitted=())


@dataclass(frozen=True)
class TranscriptPageWork(SerializedWork[PreparedTranscriptPage], ScopedWork[PreparedTranscriptPage]):
    scope: PreparationScope
    loader: Callable[..., Awaitable[TranscriptPage]]
    through: TranscriptCursor
    request: PageRequest
    lane = WorkLane.MODEL

    @property
    def work_key(self) -> WorkKey:
        return WorkKey(type(self), (self.through, self.request), self.scope)

    def result_size(self, result: PreparedTranscriptPage) -> int:
        return result.retained_bytes

    async def execute(
        self, runtime: PreparationRuntime, key: WorkKey,
    ) -> tuple[PreparedValue[PreparedTranscriptPage], int]:
        request = self.request
        page = await self.loader(before=request.before, after=request.after, through=self.through)
        cursor = request.before or request.after
        if cursor is not None:
            edge = page.before if request.before is not None else page.after
            more = page.has_older if request.before is not None else page.has_newer
            wrong_direction = (edge.contains(cursor) if request.before is not None
                               else cursor.contains(edge))
            if edge.session_file != cursor.session_file or (wrong_direction and more):
                raise ValueError("Transcript history made no cursor progress")
        if self.scope.closed:
            raise asyncio.CancelledError
        fragments = await runtime.submit(RenderPreparation(TranscriptRenderTask(page.events)))
        return await runtime.run_thread(
            lambda: self.finish_result(key, PreparedTranscriptPage(
                page, fragments, retained_bytes((page, fragments)),
            )),
        )


class TranscriptPageBuffer(PreparedPageSource):
    """Lookahead intent for a snapshot; storage/admission belong to the runtime.

    The loader retains ownership of transcript/routing semantics and off-loop
    I/O. CPU preparation uses the application's existing renderer. Foreground
    consumers share in-flight requests; cancelling one waiter cannot release a
    still-running read's admission or publish it into a closed view.
    """

    def __init__(
        self, loader: Callable[..., Awaitable[TranscriptPage]] | None, through: TranscriptCursor,
        runtime: PreparationRuntime,
    ) -> None:
        super().__init__()
        self.loader, self.through, self.runtime = loader, through, runtime
        self.scope = PreparationScope()
        self._blocked: OrderedDict[PageRequest, None] = OrderedDict()

    @property
    def closed(self) -> bool:
        return self.scope.closed

    def close(self) -> None:
        super().close()
        self._blocked.clear()

    async def get(self, request: PageRequest) -> PreparedTranscriptPage:
        if self.loader is None:
            raise ValueError("This transcript has no saved-source reader")
        result = await self.runtime.submit(TranscriptPageWork(self.scope, self.loader, self.through, request))
        self._blocked.pop(request, None)
        return result.admit()

    async def prefetch(
        self, before: TranscriptCursor | None, after: TranscriptCursor | None,
        keep_going: Callable[[], bool], *, rounds: int = 1,
    ) -> AsyncIterator[PreparedTranscriptPage]:
        """Yield read-ahead source for body preparation in the existing renderer.

        The runtime owns each retained page. Consumers prepare its actual
        leaves without copying the paging cursor into another resource owner.
        """
        from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision

        for _ in range(min(rounds, self.runtime.max_entries)):
            for older in (True, False):
                cursor = before if older else after
                if cursor is None:
                    continue
                if self.closed or not keep_going():
                    return
                request = PageRequest(before=cursor) if older else PageRequest(after=cursor)
                if request in self._blocked:
                    if older:
                        before = None
                    else:
                        after = None
                    continue
                try:
                    prepared = await self.get(request)
                except (CoordinationReadUnavailable, StaleRevision):
                    # Busy or revoked source reads cannot poison page identity.
                    # Keep mounted coverage and terminate speculative work.
                    return
                except (OSError, ValueError):
                    # A foreground request can retry/report the error. Repeated
                    # layout signals must not keep retrying speculative failures.
                    self._blocked[request] = None
                    if len(self._blocked) > self.runtime.max_entries:
                        self._blocked.popitem(last=False)
                    prepared = None
                if prepared is not None:
                    if self.closed or not keep_going():
                        return
                    yield prepared
                if older:
                    before = (prepared.page.before if prepared is not None
                              and prepared.page.has_older and prepared.retained_bytes <= self.runtime.max_bytes
                              else None)
                else:
                    after = (prepared.page.after if prepared is not None
                             and prepared.page.has_newer and prepared.retained_bytes <= self.runtime.max_bytes
                             else None)
            if before is None and after is None:
                break


class ProjectedTranscriptSource(PreparedPageSource):
    """A projected prefix with a fixed boundary and ordinary bidirectional reads.

    The boundary is the unadmitted prefix of one canonical page. Earlier reads
    stop at its native before cursor; reaching that cursor forwards returns the
    retained boundary rather than overlapping the canonical mounted tail.
    Only the boundary and the caller's bounded pages remain strongly retained.
    """

    def __init__(
        self, boundary: PreparedTranscriptPage,
        loader: Callable[..., Awaitable[TranscriptPage]] | None,
        runtime: PreparationRuntime, projection: TranscriptPageProjection,
        upstream: PreparedPageSource | None = None,
    ) -> None:
        super().__init__()
        self.loader, self.runtime, self.projection = loader, runtime, projection
        self._upstream = upstream
        self.through = boundary.page.after
        self._raw = TranscriptPageBuffer(loader, boundary.page.before, runtime) if loader is not None else None
        self.scope = self._raw.scope if self._raw is not None else PreparationScope()
        self._boundary = replace(boundary, page=replace(
            boundary.page, has_newer=False,
            has_older=boundary.page.has_older and loader is not None,
        ))
        self._projected_boundary: PreparedTranscriptPage | None = None

    async def _project(self, prepared: PreparedTranscriptPage) -> PreparedTranscriptPage:
        """Publish this source's projection only inside its original lifetime."""
        if self.closed:
            raise asyncio.CancelledError
        projected = await self.projection.project(prepared, self.runtime)
        if self.closed:
            raise asyncio.CancelledError
        return projected

    async def boundary(self) -> PreparedTranscriptPage:
        if self.closed:
            raise asyncio.CancelledError
        if self._projected_boundary is None:
            self._projected_boundary = await self._project(self._boundary)
        return self._projected_boundary

    async def get(self, request: PageRequest) -> PreparedTranscriptPage:
        if self.closed:
            raise asyncio.CancelledError
        if (request.before == self.through
                or request.after == self._boundary.page.before or self._raw is None):
            return await self.boundary()
        older = request.before is not None
        reader = (self._upstream if older and self._upstream is not None and not self._upstream.closed
                  else self._raw)
        initial = await reader.get(request)
        prepared = initial
        while True:
            prepared = await self._project(prepared)
            if prepared.fragments:
                break
            more = prepared.page.has_older if older else prepared.page.has_newer
            if not more:
                if not older:
                    boundary = await self.boundary()
                    return replace(boundary, page=replace(
                        boundary.page, before=initial.page.before,
                        has_older=initial.page.has_older,
                    ))
                break
            prepared = await reader.get(PageRequest(
                before=prepared.page.before if older else None,
                after=prepared.page.after if not older else None,
            ))
        # Unmatched intervals advance source cursors, not empty widget pages.
        # Retain the whole scanned span so reversing direction cannot skip a
        # matching record or repeatedly rediscover an empty interval.
        page = replace(
            prepared.page,
            before=prepared.page.before if older else initial.page.before,
            after=initial.page.after if older else prepared.page.after,
            has_older=prepared.page.has_older if older else initial.page.has_older,
            has_newer=True,
        )
        return replace(prepared, page=page)

    async def prefetch(
        self, before: TranscriptCursor | None, after: TranscriptCursor | None,
        keep_going: Callable[[], bool], *, rounds: int = 1,
    ) -> AsyncIterator[PreparedTranscriptPage]:
        if self.closed or not keep_going():
            return
        if self._raw is None:
            return
        limit = self._boundary.page.before
        if self._upstream is not None and not self._upstream.closed:
            async for prepared in self._upstream.prefetch(
                before if before is not None and limit.contains(before) else None,
                None, keep_going, rounds=rounds,
            ):
                prepared = await self._project(prepared)
                if not keep_going():
                    return
                yield prepared
            before = None
        if self.closed:
            return
        assert self._raw is not None
        async for prepared in self._raw.prefetch(
            before if before is not None and limit.contains(before) else None,
            after if after is not None and limit.contains(after) and after != limit else None,
            keep_going, rounds=rounds,
        ):
            prepared = await self._project(prepared)
            if not keep_going():
                return
            yield prepared

    def close(self) -> None:
        super().close()
        if self._raw is not None:
            self._raw.close()
        self._projected_boundary = None
        self._upstream = None
        self._raw = None
        self.loader = None
