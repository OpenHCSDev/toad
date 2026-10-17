"""Each filter state owns its projection, scan demand and worker lifetime."""

from __future__ import annotations

from abc import abstractmethod
from contextlib import ExitStack
from functools import partial
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from toad.widgets.message_filter import all_categories
from toad.transcript_source_preparation import HistorySourceSnapshot

if TYPE_CHECKING:
    from textual.worker import Worker
    from toad.transcript_preparation import PreparedPageSource
    from toad.widgets.transcript_history import LineHistory, ProjectedTranscriptHistory


class FilterState(DeclaredFamily, affix="Filter"):
    active = False
    overlay = None
    older_visible = False
    has_older = False
    scan_available = False

    def __init__(self, owner: LineHistory):
        self.owner = owner
        self.demand: ScanDemand = AutomaticScanDemand()
        self.worker: Worker | None = None

    @classmethod
    def for_selection(cls, owner: LineHistory) -> FilterState:
        selected = owner.selected_categories
        if selected == all_categories():
            return NoFilter(owner)
        if not selected:
            return EmptyFilter(owner)
        return SeekingFilter(owner)

    @property
    def scanning(self):
        # A cancelled PENDING worker is no longer scanning.
        return (self.worker is not None and not self.worker.is_cancelled
                and not self.worker.is_finished)

    @property
    def checkpoint_available(self):
        return not self.scanning

    def owns_projection(self, projection) -> bool:
        return False

    def owns_source(self, source: PreparedPageSource) -> bool:
        return False

    def covers_incoming(self, sequence: int) -> bool:
        return False

    def projection_visible(self) -> bool:
        return False

    async def prepare_rows(self, current, *, window, target, rows_needed: int) -> None:
        """Only a retained projection has additional rows to prepare."""

    def retire(self) -> None:
        """States without a projection have no native view to retire."""

    def remove(self) -> None:
        if self.owner.filter is self:
            self.owner.filter = FilterState.for_selection(self.owner)

    def changed(self) -> FilterState:
        owner = self.owner
        owner.invalidate_projection()
        for page in owner.pages:
            page.set_categories(owner.selected_categories)
        if self.scanning:
            self.worker.cancel()
        self.retire()
        return FilterState.for_selection(owner)

    def canonical_moved(self, previous, visible) -> None:
        pass

    def scan_needed(self) -> bool:
        return False

    def check_edges(self) -> None:
        if self.scan_needed() or self.demand.forced:
            self.start_scan()

    def request_force(self) -> None:
        self.demand = RequestedScanDemand()

    def request_older(self) -> None:
        self.request_force()
        self.start_scan()

    def start_scan(self) -> Worker | None:
        if self.scanning or not self.owner.checkpoint_available:
            return None
        if not self.scan_available:
            return None
        self.worker = self.owner.run_worker(self.scan_older, group="filtered-history")
        return self.worker

    def require_projection(self, snapshot, projection) -> None:
        from toad.widgets.transcript_history import _DrawingStopped
        if (not snapshot.current(self.owner) or self.owner.filter is not self
                or not self.owns_projection(projection)):
            raise _DrawingStopped

    def transfer_scan(self, successor: FilterState) -> None:
        """Promotion keeps the running scan with the newly published state."""
        successor.demand, self.demand = self.demand, AutomaticScanDemand()
        successor.worker, self.worker = self.worker, None

    async def advance(self, snapshot: HistorySourceSnapshot) -> bool:
        return False

    async def scan_older(self) -> None:
        owner = self.owner
        snapshot = owner.source_snapshot()
        drew = False
        try:
            if snapshot.current(owner):
                drew = await self.advance(snapshot)
        except (OSError, ValueError) as error:
            if snapshot.current(owner):
                owner.notify(str(error), title="Filtered history", severity="error")
        finally:
            if snapshot.current(owner):
                # advance may have promoted SeekingFilter to Filtered.
                current = owner.filter
                if drew or not current.has_older:
                    current.demand = AutomaticScanDemand()
                current.demand.resume(current, snapshot, drew)


class NoFilter(FilterState):
    @property
    def older_visible(self):
        return self.owner.has_older

    @property
    def has_older(self):
        return self.owner.has_older


class EmptyFilter(NoFilter):
    """No category can match; no history read is needed."""
    active = True
    older_visible = False
    has_older = False


class SeekingFilter(NoFilter):
    """A restricted selection awaiting its first prepared projection."""
    active = True

    @property
    def scan_available(self):
        return self.owner.has_older

    def scan_needed(self):
        owner = self.owner
        return (self.has_older and owner.window.scroll_y <=
                owner.window.lookahead.ahead_rows(owner.window.outer_size.height))

    async def advance(self, snapshot):
        from toad.widgets.transcript_history import ProjectedTranscriptHistory, _DrawingStopped

        owner = self.owner
        source = owner.projected_source(owner.selected_categories)
        try:
            prepared = await source.boundary()
            if not snapshot.current(owner):
                return False
            rows, limit = snapshot.window.latest_limits(owner.budget)
            await prepared.prepare_rows(
                owner, lambda: snapshot.current(owner), target=owner,
                selected=owner.selected_categories, boundary=len(prepared.fragments),
                older=True, rows_needed=rows, limit=limit,
            )
            if not snapshot.current(owner):
                return False
            projection = ProjectedTranscriptHistory(owner, source, prepared)
            async with snapshot.window.history_lock:
                if not snapshot.current(owner):
                    return False
                async with snapshot.window.preserve_history(root=owner):
                    with ExitStack() as acquisition:
                        admitted_state = Filtered(owner, projection)
                        self.transfer_scan(admitted_state)
                        owner.filter = admitted_state
                        acquisition.callback(admitted_state.remove)
                        await owner.mount(projection, before=owner.pages[0])
                        admitted_state.require_projection(snapshot, projection)
                        acquisition.pop_all()
                drew = bool(projection.fragments_in_range)
                owner._update_edges()
                projection.request_preparation()
                return drew
        except _DrawingStopped:
            return False
        finally:
            if not owner.filter.owns_source(source):
                source.close()


class Filtered(FilterState):
    active = True

    def __init__(self, owner: LineHistory, projection: ProjectedTranscriptHistory):
        super().__init__(owner)
        self.overlay = projection

    @property
    def checkpoint_available(self):
        return super().checkpoint_available and self.overlay.checkpoint_available

    def owns_projection(self, projection):
        return self.overlay is projection

    def owns_source(self, source):
        return self.overlay._reader() is source

    @property
    def has_older(self):
        return self.overlay.has_older

    @property
    def scan_available(self):
        return self.overlay.older_page_available

    def covers_incoming(self, sequence):
        return self.overlay.covers_incoming(sequence)

    def projection_visible(self):
        return bool(self.overlay.visible_fragments())

    async def prepare_rows(self, current, *, window, target, rows_needed: int) -> None:
        if rows_needed:
            await self.overlay.prepare_rows(
                current, window=window, target=target,
                selected=self.overlay.selected_categories, rows_needed=rows_needed,
            )

    def retire(self):
        self.overlay.display = False
        self.owner.run_worker(self._retire, group="filter-reset")

    async def _retire(self) -> None:
        async with self.owner.window.history_lock:
            async with self.owner.window.preserve_history(root=self.owner):
                self.remove()
        if self.owner.is_attached:
            self.owner.request_preparation()

    def remove(self):
        super().remove()
        if self.overlay.is_attached:
            self.overlay.remove()

    def canonical_moved(self, previous, visible):
        owner = self.owner
        if visible or previous == (owner.pages[0], owner.pages[0].start):
            return
        self.remove()
        owner.invalidate_projection()

    async def advance(self, snapshot):
        previous = self.overlay.pages[0]
        start, before = previous.start, previous.page.before
        await self.overlay.load_older()
        first = self.overlay.pages[0]
        return first.start < start if first is previous else before.contains(first.page.before)


class ScanDemand(DeclaredFamily, affix="ScanDemand"):
    forced = False

    def resume(self, state: FilterState, snapshot: HistorySourceSnapshot, drew: bool) -> None:
        owner = state.owner
        if snapshot.current(owner) and drew and state.has_older:
            owner.call_after_refresh(owner.request_preparation)
        else:
            self.request_next(state)

    @abstractmethod
    def request_next(self, state: FilterState) -> None: ...


class AutomaticScanDemand(ScanDemand):
    def request_next(self, state):
        if state.scan_needed():
            state.owner.call_later(state.owner.request_preparation)


class RequestedScanDemand(ScanDemand):
    forced = True

    def request_next(self, state):
        state.owner.call_later(state.start_scan)
