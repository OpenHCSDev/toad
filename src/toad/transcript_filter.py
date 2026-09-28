"""Derived filter ownership, separate from the canonical transcript widget."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING
from agent_comms.declared_family import DeclaredFamily
from toad.transcript_preparation import ProjectedTranscriptSource, PreparedTranscriptPage, CategoryProjection
from toad.widgets.message_filter import ALL_CATEGORIES

if TYPE_CHECKING:
    from toad.widgets.transcript_history import TranscriptHistory, ProjectedTranscriptHistory


class FilterState(DeclaredFamily, affix="Filter"):
    @property
    @abstractmethod
    def overlay(self): ...

    @abstractmethod
    def has_older(self, owner): ...

    @property
    @abstractmethod
    def before(self): ...


class NoFilter(FilterState):
    overlay = None
    before = None

    def has_older(self, owner):
        return owner.has_older


@dataclass(frozen=True)
class Filtered(FilterState):
    view: ProjectedTranscriptHistory

    @property
    def overlay(self):
        return self.view

    def has_older(self, owner):
        return self.overlay.has_older

    @property
    def before(self):
        return self.overlay.pages[0].page.before


class ScanState(DeclaredFamily, affix="Scan"):
    running = False
    forced = False

    @abstractmethod
    def start(self): ...

    @abstractmethod
    def finish(self): ...

    @abstractmethod
    def force(self): ...

    @abstractmethod
    def clear_force(self): ...


class IdleScan(ScanState):
    def start(self): return RunningScan()
    def finish(self): return self
    def force(self): return ForcedIdleScan()
    def clear_force(self): return self


class ForcedIdleScan(IdleScan):
    forced = True
    def start(self): return ForcedRunningScan()
    def clear_force(self): return IdleScan()


class RunningScan(ScanState):
    running = True
    def start(self): return self
    def finish(self): return IdleScan()
    def force(self): return ForcedRunningScan()
    def clear_force(self): return self


class ForcedRunningScan(RunningScan):
    forced = True
    def finish(self): return ForcedIdleScan()
    def clear_force(self): return RunningScan()


class TranscriptFilter:
    def __init__(self, owner: TranscriptHistory):
        self.owner = owner
        self.state: FilterState = NoFilter()
        self.phase: ScanState = IdleScan()

    @property
    def overlay(self): return self.state.overlay

    @property
    def before(self): return self.state.before

    @property
    def has_older(self): return self.state.has_older(self.owner)

    @property
    def scanning(self): return self.phase.running

    @property
    def force_pending(self): return self.phase.forced

    @property
    def active(self): return self.owner._selected_categories != ALL_CATEGORIES

    def clear(self): self.state = NoFilter()
    def request_force(self): self.phase = self.phase.force()
    def clear_force(self): self.phase = self.phase.clear_force()

    def changed(self) -> None:
        """Retire derived rows when the selected categories change."""
        owner = self.owner
        owner._generation += 1
        selected = owner._selected_categories
        for page in owner.pages:
            page.set_categories(selected)
        overlay = self.overlay
        self.clear()
        self.clear_force()
        if overlay is not None:
            overlay.display = False
            owner.run_worker(self.remove_overlay(overlay), group="filter-reset")
        owner._update_edges()
        owner._scroll_changed()

    async def remove_overlay(self, overlay: ProjectedTranscriptHistory) -> None:
        owner = self.owner
        async with owner.window.history_lock:
            if overlay.is_attached:
                await overlay.remove()
        if owner.is_attached:
            owner._scroll_changed()

    def scan_needed(self) -> bool:
        owner = self.owner
        # Once mounted, the projected pager alone owns edge admission. Driving
        # it from the parent too can repeatedly schedule scans while it awaits.
        return (self.overlay is None and bool(owner._selected_categories)
                and self.active and self.has_older
                and (owner.window.max_scroll_y == 0
                     or owner.window.scroll_y <= owner._prefetch_distance))

    def start_scan(self) -> None:
        owner = self.owner
        if (owner._selected_categories and self.has_older
                and not self.scanning and not owner._advancing
                and (self.overlay is None or not self.overlay._loading)):
            self.phase = self.phase.start()
            owner.run_worker(self.scan_older(), group="filtered-history")

    async def scan_older(self) -> None:
        from toad.widgets.transcript_history import ProjectedTranscriptHistory, _PublicationRetired
        owner = self.owner
        self.phase = self.phase.start()
        generation = owner._generation
        admitted = False
        source = None

        def is_current() -> bool:
            return (generation == owner._generation and owner.state.accepts_publication
                    and self.active and bool(owner._selected_categories))

        try:
            overlay = self.overlay
            if overlay is not None:
                previous = set(overlay.fragment_views)
                if not overlay._loading and overlay.has_older:
                    overlay._loading = True
                    await overlay._load_page(True)
                admitted = bool(set(overlay.fragment_views) - previous)
                return
            else:
                page = owner.pages[0]
                source = ProjectedTranscriptSource(
                    PreparedTranscriptPage(page.page, page.fragments[:page.start], 0),
                    owner.loader, owner.app.preparation, CategoryProjection(owner._selected_categories),
                    upstream=owner._reader() if owner.loader is not None else None,
                )
                prepared = await source.boundary()
            if not is_current() or owner.screen is not owner.app.screen:
                return
            async with owner.window.history_lock:
                if not is_current() or owner.screen is not owner.app.screen:
                    return
                visible = owner.screen._compositor.visible_widgets
                viewport = owner.window.content_region
                anchor = next((child for child in owner.fragment_views
                               if child in visible and visible[child][0].overlaps(viewport)), None)
                overlay = ProjectedTranscriptHistory(owner, source, prepared)
                self.state = Filtered(overlay)
                async with owner.window.preserve_history(anchor):
                    await owner.mount(overlay, before=owner.pages[0])
                    if not is_current() or self.overlay is not overlay:
                        raise _PublicationRetired
                    await overlay.admit_initial()
                    if not is_current() or self.overlay is not overlay:
                        raise _PublicationRetired
                admitted = bool(overlay.fragment_views)
                owner._update_edges()
                self.clear_force()
                if not admitted and overlay.has_older:
                    # Seed one real match when the boundary prefix is empty;
                    # later batches are owned by the child's normal edge path.
                    overlay._request_page(True)
        except _PublicationRetired:
            # The filter owner already hid/queued removal of the retired overlay.
            # Exception unwinding skips waiting for its obsolete anchor frame.
            return
        except (OSError, ValueError) as error:
            if is_current():
                owner.notify(str(error), title="Filtered history", severity="error")
        finally:
            if source is not None and (self.overlay is None or self.overlay._reader() is not source):
                source.close()
            self.phase = self.phase.finish()
            current_generation = generation == owner._generation
            if current_generation and (admitted or not self.has_older):
                self.clear_force()
            if (owner.state.accepts_publication and self.active
                    and owner.screen is owner.app.screen):
                # A page containing no routed entries has no new widget/layout
                # event to drive the next step. Explicit clicks keep scanning
                # even if the overlay is currently outside the viewport.
                if current_generation and admitted and self.has_older:
                    # Painted height, not pre-layout geometry, decides whether
                    # this result fills the viewport before reading more.
                    owner.call_after_refresh(owner._check_edges)
                elif self.force_pending:
                    owner.call_later(self.start_scan)
                elif self.scan_needed():
                    owner.call_later(owner._check_edges)
