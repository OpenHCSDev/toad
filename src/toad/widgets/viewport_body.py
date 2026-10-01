"""Viewport-owned lifetimes for reconstructible document presentation.

The document keeps its source and native measured extent. Descendant widgets,
their message pumps, subscriptions and render caches have a shorter lifetime.
The window owns admission; documents implement their own retirement/restoration.
"""

from collections import OrderedDict
from functools import partial
from weakref import WeakSet, ref
from time import monotonic
from dataclasses import dataclass, replace
import asyncio
from toad.widgets.presentation_window import DirectionalPreparation, PresentationBudget

from textual.widget import Widget
from textual._measurement import NATIVE_WIDGET_HEIGHT, height_dependency
from textual.geometry import Size
from textual.worker import WorkerCancelled


class ViewportBody:
    """Nominal contract implemented by source-owning document widgets."""

    @property
    def body_dormant(self) -> bool:
        raise NotImplementedError

    @property
    def body_measurement_stale(self) -> bool:
        raise NotImplementedError

    @property
    def body_ready(self) -> bool:
        raise NotImplementedError

    async def retire_body(self) -> bool:
        raise NotImplementedError

    async def restore_body(self) -> None:
        raise NotImplementedError

    async def prepare_body(self) -> None:
        """Warm pure work in the shared renderer without mounting widgets."""

    @property
    def retained_source_bytes(self) -> int:
        return 0

    @property
    def measured_rows(self) -> int:
        raise NotImplementedError

    @property
    def retained_widget_count(self) -> int:
        raise NotImplementedError

    @property
    def materialized_widget_count(self) -> int:
        """Current native custody, including children still awaiting removal."""
        return 1 + len(self.walk_children())


@dataclass(frozen=True)
class BodyMeasurement:
    """The native body's measured extent and last materialized resource cost."""

    width: int
    rows: int
    widgets: int = 1
    nodes_revision: int | None = None


class MeasuredViewportBody(ViewportBody):
    """Shared native extent and restoration state for body-owning widgets."""

    CACHE_HEIGHT_INDEPENDENT_BOX = True
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True

    def __init__(self, *args, **kwargs):
        self._body_dormant = False
        self._body_restoring = False
        self._body_measurement = None
        self._body_measurement_stale = False
        super().__init__(*args, **kwargs)

    @property
    def body_dormant(self) -> bool:
        return self._body_dormant

    @property
    def body_measurement_stale(self) -> bool:
        return self._body_measurement_stale

    @property
    def body_ready(self) -> bool:
        return self.is_mounted and not self._body_dormant and not self._body_restoring

    @property
    def measured_rows(self) -> int:
        return self._body_measurement.rows if self._body_measurement is not None else 0

    @property
    def retained_widget_count(self) -> int:
        if self._body_dormant:
            return self._body_measurement.widgets
        # NodeList propagates descendant custody changes to this native owner.
        # Layout/style/scroll alone do not change the count. Keep the measured
        # cost with its original extent, not another viewport resource catalog.
        measurement = self._body_measurement
        if measurement is not None and measurement.nodes_revision == self._nodes._updates:
            return measurement.widgets
        widgets = 1 + len(self.walk_children())
        if measurement is not None:
            self._body_measurement = replace(
                measurement, widgets=widgets, nodes_revision=self._nodes._updates,
            )
        return widgets

    @property
    def materialized_widget_count(self) -> int:
        # A dormant body keeps its reconstruction reservation. Its native
        # children may still be pruning or may include retained fixed widgets.
        # Count that custody without overwriting the restore reservation.
        return (super().materialized_widget_count if self._body_dormant
                else self.retained_widget_count)

    def retire_measurement(self) -> None:
        # This cost belongs to the reconstructible body, not a second viewport
        # counter. Keep it with the extent when the measured native tree retires.
        self._body_measurement = replace(
            self._body_measurement, widgets=self.retained_widget_count,
            nodes_revision=self._nodes._updates,
        )
        self._body_dormant = True

    @height_dependency(NATIVE_WIDGET_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        if self._body_dormant and self._body_measurement is not None:
            if width != self._body_measurement.width:
                self._body_measurement_stale = True
            return self._body_measurement.rows
        height = super().get_content_height(container, viewport, width)
        self._body_measurement = BodyMeasurement(
            width, height, self.retained_widget_count, self._nodes._updates,
        )
        self._body_measurement_stale = False
        return height


class ViewportPresentation:
    """Own the selected screen's window membership and paint preparation."""

    def __init__(self, screen):
        self._screen = ref(screen)
        self.windows = WeakSet()
        self.anchors = set()

    @property
    def screen(self):
        screen = self._screen()
        if screen is None:
            raise ReferenceError("The viewport presentation has been retired")
        return screen

    def release(self, window) -> None:
        """Retire native observers before their optional window leaves the DOM."""
        self.windows.discard(window)
        self.anchors.discard(window)
        self.screen.screen_layout_refresh_signal.unsubscribe(window)
        window.retire_presentation_wait()

    def request(self) -> None:
        for window in self.windows:
            window.document_viewport.request()

    def suspend(self) -> None:
        for window in self.windows:
            window.retire_presentation_wait()
            window.document_viewport.request()
        for window in self.anchors:
            window.retire_presentation_wait()

    def frame_windows(self):
        return (window for window in self.windows
                if window.document_viewport.accepts_frame())

    def has_pending_mutations(self) -> bool:
        return any(window.history_mutating() for window in self.frame_windows())

    def prepare(self) -> bool:
        screen = self.screen
        if not screen.is_current:
            return True
        if self.has_pending_mutations():
            return False
        # Visible source bodies must be ready on every frame, including rapid
        # PageDown/End frames outside a session activation.
        for window in self.frame_windows():
            if not window.document_viewport.visible_bodies_ready:
                window.document_viewport.request()
                return False
        changed = False
        for window in self.frame_windows():
            changed |= window.check_follow()
        if changed:
            # Native UpdateScroll owns reflow; do not reenter layout or paint stale geometry.
            return False
        return True


class WindowMembership:
    """One window's registration in its screen presentation."""
    def __init__(self, window):
        self.window = ref(window)
        self.presentation = window.screen.viewport_presentation
        self.presentation.windows.add(window)

    def retire(self):
        window = self.window()
        self.presentation.windows.discard(window)
        self.presentation.anchors.discard(window)


class DocumentViewport:
    """One bounded warm working set for a history window, not one per message."""

    def __init__(self, window, *, budget: PresentationBudget | None = None):
        self.budget = budget if budget is not None else PresentationBudget(
            buffer_viewports=window.app.settings.ui.history_buffer_viewports,
        )
        self.lookahead = DirectionalPreparation(self)
        self._settle_timer = None
        self._window = ref(window)
        self.owners = WeakSet()
        self._warm = OrderedDict()
        self.body_evictions = 0
        self._pending = False
        self._running = False
        self._worker = None
        self._suspended = False
        window.watch(window, "scroll_y", self.request, init=False)
        window.screen.screen_layout_refresh_signal.subscribe(window, self.request)
        self.membership = WindowMembership(window)

    @property
    def window(self):
        window = self._window()
        if window is None:
            raise ReferenceError("The document viewport's window has been retired")
        return window

    def accepts_frame(self) -> bool:
        """Only this resource's bound lifetime participates in publication."""
        return not self._suspended

    def register(self, owner: ViewportBody) -> None:
        self.owners.add(owner)
        key = ref(owner)
        self._warm[key] = key
        self.request()

    def discard(self, owner: ViewportBody) -> None:
        self.owners.discard(owner)
        self._warm.pop(ref(owner), None)

    def body_roots(self):
        """Native document order, stopping at each registered body boundary.

        Descendants belong to that body's materialization, not to another
        viewport admission. Walk the original tree without expanding those
        descendants or keeping an independent order alongside native custody.
        """
        pending = list(reversed(self.window.children))
        while pending:
            node = pending.pop()
            if node in self.owners:
                yield node
            else:
                pending.extend(reversed(node.children))

    @property
    def visible_body_rows(self) -> float:
        """Measured native density, derived from the current viewport owners."""
        visible = self.window.screen._compositor.visible_widgets
        rows = [owner.measured_rows for owner in self.body_roots()
                if owner in visible and owner.measured_rows]
        return sum(rows) / len(rows) if rows else max(1, self.window.size.height)

    def admission(self, *, required=(), ahead=()):
        # Select the bounded materialized working set BEFORE restoring a body.
        # A dormant body carries its last native cost with its measured extent.
        # Restoring everything then evicting it causes its own layouts to repeat
        # the same admission forever when the requested runway exceeds the bound.
        candidates = dict.fromkeys((*required, *ahead, *(owner
            for key in reversed(self._warm.values()) if (owner := key()) is not None)))
        roots = tuple(owner for owner in candidates
                      if not any(parent in self.owners for parent in owner.ancestors))
        return self.budget.admit(
            roots, required, self.window.size.height, self.window.app.preparation.max_bytes,
        )

    async def _trim_warm(self, *, required=(), ahead=()):
        admitted = self.admission(required=required, ahead=ahead)
        for key in tuple(self._warm):
            if key() not in admitted:
                self._warm.pop(key)
                self.body_evictions += 1
        for owner in reversed(ahead):
            if owner in admitted:
                key = ref(owner)
                self._warm[key] = key
                self._warm.move_to_end(key)
        for owner in required:
            key = ref(owner)
            self._warm[key] = key
            self._warm.move_to_end(key)
        return admitted

    def request(self, *_args) -> None:
        if self._suspended or not self.window.is_attached or self.window._closing:
            return
        self._pending = True
        if not self.window._restoring and self.lookahead.observe(self.window.scroll_y):
            self._schedule_settle()
            for history in tuple(self.window.histories):
                history.prepare_scroll()
        if not self._running:
            self._running = True
            self._worker = self.window.run_worker(partial(self._reconcile), group="viewport-bodies")

    def destination(self) -> None:
        self.lookahead.observe(self.window.scroll_y)
        self.lookahead.destination(self.window.size.height)
        self._schedule_settle()
        self.request()

    def _schedule_settle(self) -> None:
        if self._settle_timer is not None:
            self._settle_timer.stop()
        self._settle_timer = self.window.set_timer(self.lookahead.idle_seconds, self._settle)

    def _settle(self) -> None:
        self._settle_timer = None
        self.lookahead.settle()
        for history in tuple(self.window.histories):
            history.prepare_scroll()
        self.request()

    async def suspend_source(self) -> None:
        """Finish the departing source's layout transactions before rebinding."""
        self._suspended = True
        if self._settle_timer is not None:
            self._settle_timer.stop()
            self._settle_timer = None
        self.lookahead.settle()
        self._pending = False
        self.window.retire_presentation_wait()
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.cancel()
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    def resume_source(self) -> None:
        self._suspended = False
        self.request()

    async def close(self) -> None:
        """Release this working set before its window's final retirement."""
        await self.suspend_source()
        self._warm.clear()
        self.owners.clear()

    def protected(self) -> set[Widget]:
        screen = self.window.screen
        protected = set()
        endpoints = set(screen.selections)
        if screen.focused is not None:
            endpoints.add(screen.focused)
        for endpoint in endpoints:
            node = endpoint
            while isinstance(node, Widget) and node is not self.window:
                protected.add(node)
                node = node.parent
        if self.window.history_anchor is not None:
            protected.add(self.window.history_anchor.widget)
        return protected

    @property
    def visible_bodies_ready(self) -> bool:
        # Nested bodies own their readiness even when an outer fragment owns
        # their retirement. Inspect native visible custody once, rather than
        # expanding every fragment's entire materialization for every frame.
        window = self.window
        visible = self.window.screen._compositor.visible_widgets
        return all(widget.body_ready for widget in visible
                   if isinstance(widget, ViewportBody) and window in widget.ancestors)

    async def _reconcile(self) -> None:
        try:
            while self._pending and self.window.is_attached and not self.window._closing:
                self._pending = False
                screen = self.window.screen
                active = screen.is_current
                visible = screen._compositor.visible_widgets if active else {}
                protected = self.protected()
                owners = tuple(self.body_roots())
                required = tuple(owner for owner in owners if owner in visible or owner in protected)
                # Reuse the same body admission and worker. Restore only the
                # neighboring destination bodies, not every skipped record.
                sequence = owners if active else ()
                demand = self.lookahead.demand
                ahead_owners = []
                visible_indexes = [index for index, node in enumerate(sequence) if node in visible]
                if visible_indexes:
                    count = self.lookahead.admission(self.budget, self.window.size.height)
                    runway = self.budget.runway(
                        sequence, min(visible_indexes), max(visible_indexes) + 1,
                        self.window.size.height,
                    )
                    predicted = demand.neighbors(
                        sequence, min(visible_indexes), max(visible_indexes) + 1, count,
                    )
                    ahead_owners = list(dict.fromkeys(demand.body_order(runway, predicted)))
                admitted = await self._trim_warm(required=required, ahead=ahead_owners)
                warm = admitted if active else set()
                retained = protected | warm | visible.keys()
                # Restore visible source before retiring unrelated bodies.
                ordered = sorted(owners, key=lambda owner: owner not in visible)
                for owner in ordered:
                    if not owner.is_attached or owner._closing:
                        continue
                    wanted = owner in retained
                    if owner.body_dormant and wanted and owner in required:
                        anchor = next((item for item in owners if item in visible and item.is_attached), owner)
                        started = monotonic()
                        await self._restore_body(owner, anchor)
                        if owner in visible:
                            self.lookahead.delivered(monotonic() - started)
                    if (not wanted and not owner.body_dormant and owner not in self.protected()
                            and not (screen.is_current and owner in screen._compositor.visible_widgets)):
                        await owner.retire_body()
                if active:
                    # Do not materialize a runway body that cannot be retained.
                    # The original demand owns incoming direction priority.
                    ahead_owners = [owner for owner in ahead_owners if owner in admitted]
                    for first in range(0, len(ahead_owners), self.budget.admission_items):
                        if not self.lookahead.accepts(demand):
                            break
                        batch = [owner for owner in ahead_owners[first:first + self.budget.admission_items]
                                 if owner in admitted and owner.is_attached and owner.body_dormant]
                        if not batch:
                            continue
                        await asyncio.gather(*(owner.prepare_body() for owner in batch))
                        for owner in batch:
                            if not self.lookahead.accepts(demand):
                                break
                            anchor = next((item for item in owners if item in visible and item.is_attached), owner)
                            await self._restore_body(owner, anchor)
                        # Live content or a width change can change actual cost.
                        # Re-admit the completed native batch before the next one.
                        admitted = await self._trim_warm(required=required, ahead=ahead_owners)
        finally:
            self._running = False

    async def _restore_body(self, owner: ViewportBody, anchor: Widget) -> None:
        async with self.window.history_lock:
            if not self.window.is_attached or not owner.is_attached or not self.window.screen.is_current:
                return
            if owner.body_measurement_stale:
                async with self.window.preserve_history(anchor):
                    await owner.restore_body()
            else:
                await owner.restore_body()
