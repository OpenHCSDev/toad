"""Viewport-owned lifetimes for reconstructible document presentation.

The document keeps its source and native measured extent. Descendant widgets,
their message pumps, subscriptions and render caches have a shorter lifetime.
The window owns admission; documents implement their own retirement/restoration.
"""

from contextlib import AsyncExitStack, ExitStack, asynccontextmanager
from collections.abc import Awaitable, Callable, Coroutine
from collections import OrderedDict
from functools import partial
from weakref import WeakSet, ref
from time import monotonic
from dataclasses import dataclass, replace
from abc import ABC, abstractmethod
from textual.strip import Strip
from toad.rich_preparation import PreparedRichContent
from toad.work_preparation import PreparationScope, retained_bytes
import asyncio
from toad.widgets.presentation_window import (
    DirectionalPreparation, PreparationDemand, PresentationBudget,
)

from textual.widget import Widget
from textual._measurement import NATIVE_WIDGET_HEIGHT, height_dependency
from textual.geometry import Size
from textual._paint_state import PaintState
from textual.worker import WorkerCancelled
from textual.worker import Worker
from textual.await_complete import AwaitComplete


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

    def retire_body(self) -> Coroutine[None, None, bool]:
        raise NotImplementedError

    async def restore_body(self) -> bool:
        raise NotImplementedError

    async def prepare_body(self) -> None:
        """Warm pure work in the shared renderer without mounting widgets."""

    @property
    def retained_source_bytes(self) -> int:
        return 0

    @property
    def retained_paint_bytes(self) -> int:
        return 0

    def release_paint(self) -> None:
        """Release a prepared paint resource at working-set eviction."""

    @property
    def measured_rows(self) -> int:
        raise NotImplementedError

    @property
    def retained_widget_count(self) -> int:
        raise NotImplementedError

    @property
    def materialized_widget_count(self) -> int:
        """Current native custody, including children still awaiting removal."""
        return 1 + self.descendant_count


@dataclass(frozen=True)
class BodyMeasurement(ABC):
    """One body's extent, native custody and prepared paint resource."""

    width: int = 0
    rows: int = 0
    widgets: int = 1

    @property
    @abstractmethod
    def dormant(self) -> bool: ...

    @abstractmethod
    def ready(self, body) -> bool: ...

    @abstractmethod
    def cost(self, body) -> int: ...

    @property
    def paint_bytes(self) -> int:
        return 0

    @abstractmethod
    def height(self, body, width, measure) -> int: ...

    @abstractmethod
    def render(self, body, crop, render_live) -> list[Strip]: ...

    @abstractmethod
    async def restore(self, body) -> None: ...

    def invalidated(self):
        return MeasuredBody(self.width, self.rows, self.widgets)

    async def materialize(self, body):
        await body.start_materialization(self).materialize(body)

    async def before_publication(self) -> None:
        """Settled resources have no outstanding native writer to join."""

    def released(self):
        return self

    def style_updated(self, body):
        return self

    def resized(self, size):
        return self

    async def retire(self, body):
        return False


@dataclass(frozen=True)
class LiveBody(BodyMeasurement):
    def invalidated(self):
        # The original native tree still carries its pixels. Replace the
        # captured lifetime so an in-flight retirement cannot publish old rows.
        return replace(self)

    @property
    def dormant(self):
        return False

    def ready(self, body):
        return body.native_body_ready()

    def cost(self, body):
        return body.materialized_widget_count

    def height(self, body, width, measure):
        height = measure()
        if (width, height) != (self.width, self.rows):
            body._body_measurement = replace(self, width=width, rows=height)
        return height

    def render(self, body, crop, render_live):
        return render_live(crop)

    async def restore(self, body):
        return

    async def materialize(self, body):
        return

    def retire(self, body):
        return body.retire_native_body(self)


@dataclass(frozen=True)
class MeasuredBody(BodyMeasurement):
    @property
    def dormant(self):
        return True

    def ready(self, body):
        return False

    def cost(self, body):
        return self.widgets

    def height(self, body, width, measure):
        return self.rows

    def render(self, body, crop, render_live):
        # This state has extent but no pixels; the original frame owner waits
        # for reconstruction. It must not treat measurement as paint coverage.
        return render_live(crop)

    async def restore(self, body):
        await body.materialize_body()


@dataclass(frozen=True, kw_only=True)
class MaterializingBody(MeasuredBody):
    """The original native worker, not a copied restoring flag."""

    worker: Worker

    def invalidated(self):
        return self

    async def materialize(self, body):
        await self.before_publication()

    async def before_publication(self) -> None:
        await self.worker.wait()


@dataclass(frozen=True, kw_only=True)
class RenderedBody(BodyMeasurement):
    content: PreparedRichContent
    resource_bytes: int
    style_revision: int
    paint_state: PaintState

    @property
    def dormant(self):
        return True

    def ready(self, body):
        # Screen commits sizes only for its current layout/exposed widgets.
        # An offscreen widget's last committed size is not a new width demand.
        # Measurement and actual size commits invalidate this resource below.
        return (body.native_body_ready() and self.style_revision == body._subtree_style_revision
                and self.paint_state == body._resolved_paint_state())

    def style_updated(self, body):
        return self if self.ready(body) else self.invalidated()

    def resized(self, size):
        return self if size.width == self.content.width else self.invalidated()

    def cost(self, body):
        return body.materialized_widget_count

    @property
    def paint_bytes(self):
        return self.resource_bytes

    def height(self, body, width, measure):
        if width != self.width:
            body.invalidate_body()
        return self.rows

    def render(self, body, crop, render_live):
        selection = body.text_selection
        return self.content.render_lines(
            crop, selection=selection,
            selection_style=body.selection_style if selection is not None else None)

    def released(self):
        return MeasuredBody(self.width, self.rows, self.widgets)

    async def restore(self, body):
        if not self.ready(body):
            body.invalidate_body()
            await body.materialize_body()


class MeasuredViewportBody(ViewportBody):
    """The body owns Live, Rendered and Measured behavior, not copied flags."""

    CACHE_HEIGHT_INDEPENDENT_BOX = True
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True
    CACHE_SUBTREE_GEOMETRY = True

    def __init__(self, *args, **kwargs):
        self._body_measurement = LiveBody()
        self._body_scope = PreparationScope()
        self._body_viewport = None
        super().__init__(*args, **kwargs)

    @property
    def body_dormant(self):
        return self._body_measurement.dormant

    @property
    def body_measurement_stale(self):
        return not self._body_measurement.ready(self)

    @property
    def body_ready(self):
        return self._body_measurement.ready(self)

    def native_body_ready(self):
        return self.is_mounted and not self._closing

    @property
    def measured_rows(self):
        return self._body_measurement.rows

    @property
    def retained_widget_count(self):
        return self._body_measurement.cost(self)

    @property
    def retained_paint_bytes(self):
        return self._body_measurement.paint_bytes

    def release_paint(self):
        self._body_measurement = self._body_measurement.released()

    def invalidate_body(self):
        self._body_measurement = self._body_measurement.invalidated()
        if self._body_viewport is not None:
            self._body_viewport.request()

    def _update_body_measurement(self, measurement):
        if measurement is self._body_measurement:
            return
        self._body_measurement = measurement
        if self._body_viewport is not None:
            self._body_viewport.request()

    def native_body_committed(self):
        previous = self._body_measurement
        self._body_measurement = LiveBody(previous.width, previous.rows, previous.widgets)
        self.refresh(layout=True)

    def notify_style_update(self):
        super().notify_style_update()
        # Notification is not a rule mutation. Retained rows depend on the
        # original subtree rule epoch and inherited native paint values.
        self._update_body_measurement(self._body_measurement.style_updated(self))

    def _size_updated(self, size, virtual_size, container_size, layout=True):
        changed = super()._size_updated(size, virtual_size, container_size, layout)
        self._update_body_measurement(self._body_measurement.resized(size))
        return changed

    @property
    def selection_style(self):
        from textual.style import Style
        return Style.from_styles(self.screen.get_component_styles('screen--selection')).rich_style

    def render_lines(self, crop):
        return self._body_measurement.render(self, crop, super().render_lines)

    def get_selection(self, selection):
        if self.body_dormant and self.body_ready:
            return selection.extract(self._body_measurement.content.text), '\n'
        return super().get_selection(selection)

    async def prepare_input(self, event):
        # Native controls are actual resources, not pixels. Restore them at
        # interaction, retaining read-only rows for ordinary scroll/reentry.
        if self.body_dormant:
            await self.materialize_body()
            # Native input routing must select its target after the new scene
            # commits, outside the mutation lock; no synthetic event replay.
            painted = asyncio.Event()
            self.screen.call_after_refresh(painted.set)
            await painted.wait()

    async def materialize_body(self):
        if not self.body_dormant or not self.is_attached or self._closing:
            return
        await self._body_measurement.materialize(self)

    def publish_body(self, work: Callable[[], Awaitable[None]]) -> AwaitComplete:
        """Source updates and reentry share the original materialization worker."""
        operation = self.start_materialization(self._body_measurement, work)
        return AwaitComplete(operation.materialize(self))

    def start_materialization(self, previous, work=None):
        async def materialize():
            try:
                # Identity guards prevent an old commit; joining its actual
                # worker also prevents old native writes after the new commit.
                await previous.before_publication()
                await (self.materialize_native_body() if work is None else work())
                if self.is_attached and self._body_measurement is current:
                    self.native_body_committed()
            except BaseException:
                if self._body_measurement is current:
                    self._body_measurement = MeasuredBody(
                        previous.width, previous.rows, previous.widgets)
                raise

        worker = self.run_worker(materialize(), group="body-materialization", exit_on_error=False)
        current = MaterializingBody(previous.width, previous.rows, previous.widgets, worker=worker)
        self._body_measurement = current
        return current

    async def materialize_native_body(self):
        raise NotImplementedError

    def reconstructible_children(self):
        raise NotImplementedError

    def retire_body_resources(self):
        pass

    def retire_body(self):
        # Acquire pixels synchronously. The viewport can capture its bounded
        # cohort from one publication before any preparation or pruning awaits.
        return self._body_measurement.retire(self)

    @asynccontextmanager
    async def retirement_custody(self):
        async with self.lock:
            yield True

    def retire_native_body(self, current):
        if not self.body_ready or not self.is_attached:
            return BodyMeasurement.retire(current, self)
        if self.lock.is_locked or self._body_viewport is None:
            return BodyMeasurement.retire(current, self)
        if self in self._body_viewport.protected():
            return BodyMeasurement.retire(current, self)
        children = self.reconstructible_children()
        if not children or any(not child.body_ready for child in self.walk_children()
                               if isinstance(child, ViewportBody)):
            return BodyMeasurement.retire(current, self)
        compositor = self.screen._compositor
        style_revision = self._subtree_style_revision
        paint_state = self._resolved_paint_state()
        captured = tuple(compositor.published_geometry((self,)))
        if not captured:
            return BodyMeasurement.retire(current, self)
        _body, placement = captured[0]
        size, rows = compositor.render_subtree_strips(self, placement)
        # Native capture already owns final styled terminal rows. Retain those
        # rows directly; rendering them again in Rich workers duplicates work
        # and serializes a resource that never leaves this process.
        content = PreparedRichContent(size.width, tuple(rows))
        return self.finish_native_retirement(current, children, content, style_revision, paint_state)

    async def finish_native_retirement(self, current, children, content, style_revision, paint_state):
        size_bytes = await self.app.preparation.run_thread(retained_bytes, content)
        # The original state is the captured source/width/style lifetime. An
        # asynchronous change invalidates it rather than copying a revision.
        if self._body_measurement is not current or not self.is_attached or self._closing:
            return False
        rendered = RenderedBody(
            current.width, current.rows, self.materialized_widget_count,
            content=content, resource_bytes=size_bytes,
            style_revision=style_revision, paint_state=paint_state,
        )
        if not rendered.ready(self):
            return False
        async with self.retirement_custody() as can_commit:
            if (not can_commit or self._body_measurement is not current or not rendered.ready(self)
                    or not self.is_attached or self._closing
                    or self._body_viewport is None
                    or self in self._body_viewport.protected()):
                return False
            self._body_measurement = rendered
            self.retire_body_resources()
            await self.remove_children(children)
            self.refresh(layout=True)
        return True

    async def restore_body(self):
        previous = self._body_measurement
        await previous.restore(self)
        return self._body_measurement is not previous

    @height_dependency(NATIVE_WIDGET_HEIGHT)
    def get_content_height(self, container, viewport, width):
        native_height = super().get_content_height
        return self._body_measurement.height(
            self, width, lambda: native_height(container, viewport, width))

    def get_content_width(self, container, viewport):
        if self.body_dormant:
            return self._body_measurement.width
        return super().get_content_width(container, viewport)

    def on_unmount(self):
        if self._body_viewport is not None:
            self._body_viewport.discard(self)
            self.app.preparation.discard_scope(self._body_scope)
            self._body_viewport = None
        self._body_scope.closed = True
        self._body_measurement = LiveBody()

    def on_mount(self):
        from toad.screens.workspace import WorkspaceScreen
        from toad.widgets.history_anchor import HistoryWindow
        if isinstance(self.screen, WorkspaceScreen):
            for ancestor in self.ancestors:
                if isinstance(ancestor, ViewportBody):
                    return
                if isinstance(ancestor, HistoryWindow):
                    self._body_viewport = ancestor.document_viewport
                    self._body_viewport.register(self)
                    return


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

    def geometry_targets(self) -> tuple[Widget, ...]:
        """Keep reader anchors and live body boxes in the same native layout.

        Capturing an offscreen body needs its current box, not another full
        scene arrangement. Retained rows already own their extent; they do not
        require a live descendant layout just to scroll back into view.
        """
        return tuple(dict.fromkeys((
            *(target for window in self.anchors
              for target in window.history_geometry_targets()),
            *(target for window in self.frame_windows()
              for target in window.document_viewport.geometry_targets()),
        )))

    def has_pending_mutations(self, windows) -> bool:
        return any(window.history_mutating() for window in windows)

    def prepare(self) -> bool:
        screen = self.screen
        if not screen.is_current:
            return True
        # This synchronous admission consumes one cohort from the original
        # membership owner. Mutation, body readiness and follow checks don't
        # independently select the same windows again within the same frame.
        windows = tuple(self.frame_windows())
        if self.has_pending_mutations(windows):
            return False
        # Visible source bodies must be ready on every frame, including rapid
        # PageDown/End frames outside a session activation.
        for window in windows:
            if not window.document_viewport.visible_bodies_ready:
                window.document_viewport.request()
                return False
        changed = False
        for window in windows:
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

    def bind(self, presentation):
        self.retire()
        self.presentation = presentation
        self.presentation.windows.add(self.window())

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
        self.admitted_bodies = set()
        self.body_evictions = 0
        self._pending = False
        self._running = False
        self._worker = None
        self._suspended = False
        window.watch(window, "scroll_y", self.scroll_changed, init=False)
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
        # Declare custody before layout so its live box is a geometry target.
        # Preparation consumes the committed frame, not a partially mounted
        # tree whose geometry query would manufacture a full-scene layout.
        # The existing frame owner batches this window's initial callbacks and
        # the native message pump revokes them when the window is retired.
        self.window.screen.frame_presentation.defer(self.window, self.request)

    def discard(self, owner: ViewportBody) -> None:
        self.owners.discard(owner)
        self._warm.pop(ref(owner), None)
        self.admitted_bodies.discard(owner)

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

    def geometry_targets(self) -> tuple[Widget, ...]:
        """Native controls retain their box until their body captures its rows."""
        return tuple(owner for owner in self.owners if not owner.body_dormant)

    @property
    def materialized_widget_count(self) -> int:
        """Actual native body custody in this window's resource scope."""
        return sum(owner.materialized_widget_count for owner in self.owners)

    @property
    def visible_body_rows(self) -> float:
        """Measured native density, derived from the current viewport owners."""
        visible = self.window.screen._compositor.visible_widgets
        rows = [owner.measured_rows for owner in visible
                if owner in self.owners and owner.measured_rows]
        return sum(rows) / len(rows) if rows else max(1, self.window.size.height)

    def admission(self, *, required=(), ahead=()):
        # Select the bounded materialized working set BEFORE restoring a body.
        # A dormant body carries its last native cost with its measured extent.
        # Restoring everything then evicting it causes its own layouts to repeat
        # the same admission forever when the requested runway exceeds the bound.
        candidates = dict.fromkeys((*required, *ahead, *(owner
            for key in reversed(self._warm.values()) if (owner := key()) is not None)))
        # Mount already admits only the outer body into this viewport. Native
        # membership owns that boundary; consumers don't rediscover its parents.
        roots = tuple(owner for owner in candidates if owner in self.owners)
        return self.budget.admit(
            roots, required, self.window.size.height, self.window.app.preparation.max_bytes,
        )

    def _trim_warm(self, *, required=(), ahead=()):
        self.admitted_bodies = self.admission(required=required, ahead=ahead)
        admitted = self.admitted_bodies
        for key in tuple(self._warm):
            if key() not in admitted:
                owner = key()
                if owner is not None:
                    owner.release_paint()
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
        if not self._running:
            self._running = True
            self._worker = self.window.run_worker(partial(self._reconcile), group="viewport-bodies")

    def scroll_changed(self, *_args) -> None:
        # Native scroll is the demand producer. Screen-wide layout (including
        # this working set's own pruning) is not another scroll or admission.
        if (self._suspended or not self.window.is_attached
                or self.window._closing or self.window._restoring):
            return
        if self.lookahead.observe(self.window.scroll_y):
            self._schedule_settle()
            for history in tuple(self.window.histories):
                history.prepare_scroll()
        self.request()

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
        # Resume restores the native geometry target declaration as well as
        # source custody. Reconciliation consumes that publication; it must
        # not capture from the departing/parked scene or manufacture its boxes.
        if self.geometry_targets():
            self.window.refresh(layout=True)
        self.window.screen.frame_presentation.defer(self.window, self.request)

    async def close(self) -> None:
        """Release this working set before its window's final retirement."""
        await self.suspend_source()
        self._warm.clear()
        self.owners.clear()
        self.admitted_bodies.clear()

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
                admitted = self._trim_warm(required=required, ahead=ahead_owners)
                # Admission retains a body's bounded presentation resource,
                # not its live descendant tree. Offscreen warm bodies paint
                # their retained rows on reentry; only visible or interaction
                # protected bodies need their current native controls.
                retained = protected | visible.keys()
                # One foreground cohort produces readiness before frame
                # admission. Per-body paint waits would hold this worker while
                # the remaining visible dormant bodies reject that same frame.
                restoring = tuple(owner for owner in required
                                  if owner.is_attached and not owner._closing and owner.body_dormant and not owner.body_ready)
                restored = ()
                if restoring:
                    anchor = next((item for item in owners if item in visible and item.is_attached), restoring[0])
                    started = monotonic()
                    restored = await self._restore_bodies(restoring, anchor, demand)
                    if any(owner in visible for owner in restored):
                        self.lookahead.delivered(monotonic() - started)
                retiring = tuple(owner for owner in owners
                                 if owner.is_attached and not owner._closing
                                 and owner not in retained and not owner.body_dormant)
                retired_owners = []
                for first in range(0, len(retiring), self.budget.admission_items):
                    # Each call captures its original rows now; tasks only
                    # prepare detached rows and validate/prune afterward.
                    batch = retiring[first:first + self.budget.admission_items]
                    with ExitStack() as captures:
                        operations = []
                        for owner in batch:
                            operation = owner.retire_body()
                            captures.callback(operation.close)
                            operations.append(operation)
                        async with asyncio.TaskGroup() as preparations:
                            tasks = [preparations.create_task(operation)
                                     for operation in operations]
                        results = [task.result() for task in tasks]
                    for owner, retired in zip(batch, results):
                        if retired:
                            retired_owners.append(owner)
                            key = ref(owner)
                            self._warm[key] = key
                            self._warm.move_to_end(key)
                    if any(results):
                        # Pruning retires the old scene. Continue from the next
                        # published layout, never lazily arrange it for capture.
                        screen.frame_presentation.defer(self.window, self.request)
                # Capturing rows changes the original body resource cost.
                # The same warm LRU admits or releases that paint resource.
                if retired_owners or restored:
                    admitted = self._trim_warm(required=required, ahead=ahead_owners)
                if active:
                    # Do not materialize a runway body that cannot be retained.
                    # The original demand owns incoming direction priority.
                    ahead_owners = [owner for owner in ahead_owners if owner in admitted]
                    for first in range(0, len(ahead_owners), self.budget.admission_items):
                        if not self.lookahead.accepts(demand):
                            break
                        batch = [owner for owner in ahead_owners[first:first + self.budget.admission_items]
                                 if owner in admitted and owner.is_attached and owner.body_dormant and not owner.body_ready]
                        if not batch:
                            continue
                        await asyncio.gather(*(owner.prepare_body() for owner in batch))
                        anchor = next((item for item in owners if item in visible and item.is_attached), batch[0])
                        restored = await self._restore_bodies(tuple(batch), anchor, demand)
                        # Live content or a width change can change actual cost.
                        # Re-admit the completed native batch before the next one.
                        if restored:
                            admitted = self._trim_warm(required=required, ahead=ahead_owners)
        finally:
            self._running = False

    async def _restore_bodies(
        self, owners: tuple[ViewportBody, ...], anchor: Widget, demand: PreparationDemand,
    ) -> tuple[ViewportBody, ...]:
        if (not self.window.is_attached or not self.window.screen.is_current
                or not self.lookahead.accepts(demand)):
            return ()
        owners = tuple(owner for owner in owners if owner.is_attached and not owner._closing)
        restored = []
        async with AsyncExitStack() as mutation:
            if any(owner.body_measurement_stale for owner in owners):
                await mutation.enter_async_context(self.window.preserve_reader(anchor))
            for owner in owners:
                if not self.window.screen.is_current or not self.lookahead.accepts(demand):
                    break
                if owner.is_attached and not owner._closing:
                    if await owner.restore_body():
                        restored.append(owner)
        if restored:
            # Native child composition and nested page publication produce
            # readiness. The same frame owns capture after compensated layout.
            self.window.screen.frame_presentation.defer(self.window, self.request)
        return tuple(restored)
