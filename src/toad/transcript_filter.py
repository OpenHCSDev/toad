"""Declared projection and scan demand own derived transcript filtering."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from toad.widgets.message_filter import all_categories

if TYPE_CHECKING:
    from collections.abc import Callable
    from textual.screen import Screen
    from textual.worker import Worker
    from toad.transcript_preparation import PreparedPageSource
    from toad.widgets.conversation import Window
    from toad.widgets.message_filter import MessageCategory
    from toad.widgets.transcript_history import TranscriptHistory, ProjectedTranscriptHistory


@dataclass(frozen=True)
class FilterSnapshot:
    """One publication identity, captured by the canonical history owner."""

    generation: int
    selected: frozenset[type[MessageCategory]]
    window: Window
    loader: Callable | None
    screen: Screen

    def current(self, owner: TranscriptHistory) -> bool:
        if not owner.filter_publication_available:
            return False
        return self == owner.filter_snapshot()


class FilterState(DeclaredFamily, affix="Filter"):
    overlay = None
    before = None
    checkpoint_available = True

    def owns_projection(self, projection) -> bool:
        return False

    def older_visible(self, owner) -> bool:
        return False

    async def canonical_moved(self, filtering, previous, visible) -> None:
        pass

    def owns_source(self, source: PreparedPageSource) -> bool:
        return False

    def covers_incoming(self, sequence: int) -> bool:
        return False

    def visible(self, owner: TranscriptHistory) -> bool:
        return False

    def retire(self, filtering: TranscriptFilter) -> None:
        pass

    async def remove(self, owner: TranscriptHistory) -> None:
        pass

    @abstractmethod
    def has_older(self, owner: TranscriptHistory) -> bool: ...

    @abstractmethod
    def scan_available(self, owner: TranscriptHistory) -> bool: ...

    @abstractmethod
    def scan_needed(self, owner: TranscriptHistory) -> bool: ...

    @abstractmethod
    async def advance(self, filtering: TranscriptFilter, snapshot: FilterSnapshot) -> bool: ...


class NoFilter(FilterState):
    def older_visible(self, owner):
        return owner.has_older

    def has_older(self, owner):
        return owner.has_older

    def scan_available(self, owner):
        return owner.has_older

    def scan_needed(self, owner):
        # Once mounted, the projection's ordinary pager owns edge admission.
        return owner.window.scroll_y <= owner._prefetch_distance

    async def advance(self, filtering, snapshot):
        from toad.widgets.transcript_history import ProjectedTranscriptHistory, _PublicationRetired

        owner = filtering.owner
        source = owner.projected_source(snapshot.selected)
        try:
            prepared = await source.boundary()
            if not snapshot.current(owner):
                return False
            async with snapshot.window.history_lock:
                if not snapshot.current(owner):
                    return False
                visible = snapshot.screen._compositor.visible_widgets
                viewport = snapshot.window.content_region
                anchor = next((child for child in owner.fragment_views
                               if child in visible and visible[child][0].overlaps(viewport)), None)
                projection = ProjectedTranscriptHistory(owner, source, prepared)
                filtering.state = Filtered(projection)
                async with snapshot.window.preserve_history(anchor):
                    await owner.mount(projection, before=owner.pages[0])
                    filtering.require_projection(snapshot, projection)
                    await projection.admit_initial()
                    filtering.require_projection(snapshot, projection)
                admitted = bool(projection.fragment_views)
                owner._update_edges()
                if not admitted:
                    projection.request_older()
                return admitted
        except _PublicationRetired:
            return False
        finally:
            if not filtering.state.owns_source(source):
                source.close()


@dataclass(frozen=True)
class Filtered(FilterState):
    view: ProjectedTranscriptHistory

    @property
    def overlay(self):
        return self.view

    @property
    def before(self):
        return self.view.pages[0].page.before

    @property
    def checkpoint_available(self):
        return self.view.checkpoint_available

    def owns_projection(self, projection):
        return self.view is projection

    def owns_source(self, source):
        return self.view._reader() is source

    def has_older(self, owner):
        return self.view.has_older

    def scan_available(self, owner):
        return self.view.older_page_available

    def scan_needed(self, owner):
        return False

    def covers_incoming(self, sequence):
        return self.view.covers_incoming(sequence)

    def visible(self, owner):
        visible = owner.screen._compositor.visible_widgets
        viewport = owner.window.content_region
        return any(child in visible and visible[child][0].overlaps(viewport)
                   for child in self.view.fragment_views)

    def retire(self, filtering):
        self.view.display = False
        filtering.owner.run_worker(partial(filtering.retire, self), group="filter-reset")

    async def remove(self, owner):
        if self.view.is_attached:
            await self.view.remove()

    async def canonical_moved(self, filtering, previous, visible):
        owner = filtering.owner
        if visible or previous == (owner.pages[0], owner.pages[0].start):
            return
        # Eviction must expose the newly omitted interval, not skip it with
        # the projection's previously accepted backward cursor.
        await filtering.remove()
        owner._generation += 1

    async def advance(self, filtering, snapshot):
        previous = set(self.view.fragment_views)
        await self.view.load_older()
        return bool(set(self.view.fragment_views) - previous)


class ScanDemand(DeclaredFamily, affix="ScanDemand"):
    forced = False

    def resume(self, filtering: TranscriptFilter, snapshot: FilterSnapshot, admitted: bool) -> None:
        owner = filtering.owner
        if not owner.filter_publication_available:
            return
        if snapshot.current(owner) and admitted and filtering.has_older:
            # Committed painted height decides whether this batch fills the view.
            owner.call_after_refresh(owner._check_edges)
        else:
            self.request_next(filtering)

    @abstractmethod
    def request_next(self, filtering: TranscriptFilter) -> None: ...


class AutomaticScanDemand(ScanDemand):
    def request_next(self, filtering):
        if filtering.scan_needed():
            filtering.owner.call_later(filtering.owner._check_edges)


class RequestedScanDemand(ScanDemand):
    forced = True

    def request_next(self, filtering):
        filtering.owner.call_later(filtering.start_scan)


class TranscriptFilter:
    def __init__(self, owner: TranscriptHistory):
        self.owner = owner
        self.state: FilterState = NoFilter()
        self.demand: ScanDemand = AutomaticScanDemand()
        self.worker: Worker | None = None

    @property
    def overlay(self): return self.state.overlay

    @property
    def before(self): return self.state.before

    @property
    def has_older(self): return self.state.has_older(self.owner)

    @property
    def scanning(self):
        # Cancellation before _run enters sets the framework cancellation flag
        # without transitioning its PENDING enum. It has no admission authority.
        return (self.worker is not None and not self.worker.is_cancelled
                and not self.worker.is_finished)

    @property
    def active(self): return self.owner._selected_categories != all_categories()

    @property
    def checkpoint_available(self):
        return not self.scanning and self.state.checkpoint_available

    def owns_projection(self, projection): return self.state.owns_projection(projection)
    @property
    def older_visible(self): return self.state.older_visible(self.owner)

    async def canonical_moved(self, previous, visible):
        await self.state.canonical_moved(self, previous, visible)

    def covers_incoming(self, sequence): return self.state.covers_incoming(sequence)
    def projection_visible(self): return self.state.visible(self.owner)
    def request_force(self): self.demand = RequestedScanDemand()
    def clear(self): self.state = NoFilter()

    async def remove(self) -> None:
        retired = self.state
        self.clear()
        await retired.remove(self.owner)

    async def retire(self, retired: FilterState) -> None:
        async with self.owner.window.history_lock:
            await retired.remove(self.owner)
        if self.owner.is_attached:
            self.owner._scroll_changed()

    def changed(self) -> None:
        owner = self.owner
        owner._generation += 1
        for page in owner.pages:
            page.set_categories(owner._selected_categories)
        retired = self.state
        retired.retire(self)
        self.clear()
        self.demand = AutomaticScanDemand()
        if self.scanning:
            self.worker.cancel()
        owner._update_edges()
        owner._scroll_changed()

    def scan_needed(self) -> bool:
        if not self.active or not self.owner._selected_categories:
            return False
        return self.has_older and self.state.scan_needed(self.owner)

    def check_edges(self) -> None:
        if self.scan_needed() or self.demand.forced:
            self.start_scan()

    def request_older(self) -> None:
        self.request_force()
        self.start_scan()

    def start_scan(self) -> Worker | None:
        if self.scanning or not self.owner.filter_scan_available:
            return None
        if not self.active or not self.owner._selected_categories:
            return None
        if not self.state.scan_available(self.owner):
            return None
        self.worker = self.owner.run_worker(self.scan_older, group="filtered-history")
        return self.worker

    def require_projection(self, snapshot, projection) -> None:
        from toad.widgets.transcript_history import _PublicationRetired
        if not snapshot.current(self.owner) or not self.owns_projection(projection):
            raise _PublicationRetired

    async def scan_older(self) -> None:
        snapshot = self.owner.filter_snapshot()
        admitted = False
        try:
            if snapshot.current(self.owner):
                admitted = await self.state.advance(self, snapshot)
        except (OSError, ValueError) as error:
            if snapshot.current(self.owner):
                self.owner.notify(str(error), title="Filtered history", severity="error")
        finally:
            if snapshot.current(self.owner):
                if admitted or not self.has_older:
                    self.demand = AutomaticScanDemand()
            self.demand.resume(self, snapshot, admitted)
