"""Viewport-owned lifetimes for reconstructible document presentation.

The document keeps its source and native measured extent. Descendant widgets,
their message pumps, subscriptions and render caches have a shorter lifetime.
The window owns admission; documents implement their own retirement/restoration.
"""

from collections import OrderedDict
from functools import partial
from weakref import WeakSet, ref
from time import monotonic
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


class MeasuredViewportBody(ViewportBody):
    """Shared native extent and restoration state for body-owning widgets."""

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
        return not self._body_dormant and not self._body_restoring

    @property
    def measured_rows(self) -> int:
        return self._body_measurement[1] if self._body_measurement is not None else 0

    @height_dependency(NATIVE_WIDGET_HEIGHT)
    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        if self._body_dormant and self._body_measurement is not None:
            if width != self._body_measurement[0]:
                self._body_measurement_stale = True
            return self._body_measurement[1]
        height = super().get_content_height(container, viewport, width)
        self._body_measurement = width, height
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

    def __init__(self, window, *, budget: PresentationBudget = PresentationBudget()):
        self.budget = budget
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

    async def _trim_warm(self) -> None:
        # No suspension or DOM mutation occurs in this pass. Measure each
        # native tree once, then subtract its cost as the existing LRU retires
        # it. Recounting every survivor after every eviction is quadratic.
        costs = [(owner.retained_source_bytes, 1 + len(owner.walk_children()))
                 if (owner := key()) is not None else (0, 0)
                 for key in self._warm.values()]
        source_bytes = sum(size for size, _ in costs)
        widget_count = sum(count for _, count in costs)
        for size, count in costs:
            if (source_bytes <= self.window.app.preparation.max_bytes and
                    widget_count <= self.budget.widget_limit(self.window.size.height)):
                break
            self._warm.popitem(last=False)
            self.body_evictions += 1
            source_bytes -= size
            widget_count -= count

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
        if not self.owners:
            return True
        visible = self.window.screen._compositor.visible_widgets
        return all(widget.body_ready for widget in visible if widget in self.owners)

    async def _reconcile(self) -> None:
        try:
            while self._pending and self.window.is_attached and not self.window._closing:
                self._pending = False
                screen = self.window.screen
                active = screen.is_current
                visible = screen._compositor.visible_widgets if active else {}
                protected = self.protected()
                owners = tuple(owner for owner in self.owners if owner.is_attached)
                for owner in owners:
                    if owner in visible:
                        key = ref(owner)
                        self._warm[key] = key
                        self._warm.move_to_end(key)
                await self._trim_warm()
                warm = {key() for key in self._warm.values()} if active else set()
                retained = protected | warm | visible.keys()
                # Reuse the same body admission and worker. Restore only the
                # neighboring destination bodies, not every skipped record.
                sequence = ([node for node in self.window.walk_children() if node in self.owners]
                            if active and self.lookahead.travel_rows else [])
                ahead_owners = []
                visible_indexes = [index for index, node in enumerate(sequence) if node in visible]
                if visible_indexes:
                    ahead = self.lookahead.ahead_rows(self.window.size.height)
                    heights = [sequence[index].measured_rows for index in visible_indexes
                               if sequence[index].measured_rows]
                    extent = max(1, sum(heights) / len(heights)) if heights else self.window.size.height
                    count = min(self.budget.item_limit(0), int(ahead / max(1, extent)) + bool(ahead))
                    ahead_owners = self.lookahead.demand.neighbors(
                        sequence, min(visible_indexes), max(visible_indexes) + 1, count,
                    )
                # Restore visible source before retiring unrelated bodies.
                ordered = sorted(owners, key=lambda owner: owner not in visible)
                for owner in ordered:
                    if not owner.is_attached or owner._closing:
                        continue
                    wanted = owner in retained
                    if owner.body_dormant and wanted:
                        anchor = next((item for item in owners if item in visible and item.is_attached), owner)
                        await self._restore_body(owner, anchor)
                    if (not wanted and not owner.body_dormant and owner not in self.protected()
                            and not (screen.is_current and owner in screen._compositor.visible_widgets)):
                        await owner.retire_body()
                if active:
                    demand = self.lookahead.demand
                    for first in range(0, len(ahead_owners), self.budget.admission_items):
                        if not self.lookahead.accepts(demand):
                            break
                        batch = [owner for owner in ahead_owners[first:first + self.budget.admission_items]
                                 if owner.is_attached and owner.body_dormant]
                        if not batch:
                            continue
                        await asyncio.gather(*(owner.prepare_body() for owner in batch))
                        for owner in batch:
                            if not self.lookahead.accepts(demand):
                                break
                            anchor = next((item for item in owners if item in visible and item.is_attached), owner)
                            await self._restore_body(owner, anchor)
                            # Retention remains the existing measured working set.
                            key = ref(owner)
                            self._warm[key] = key
                            self._warm.move_to_end(key)
                            await self._trim_warm()
        finally:
            self._running = False

    async def _restore_body(self, owner: ViewportBody, anchor: Widget) -> None:
        started = monotonic()
        async with self.window.history_lock:
            if not self.window.is_attached or not owner.is_attached or not self.window.screen.is_current:
                return
            if owner.body_measurement_stale:
                async with self.window.preserve_history(anchor):
                    await owner.restore_body()
            else:
                await owner.restore_body()
        self.lookahead.delivered(monotonic() - started)
