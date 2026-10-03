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
from toad.work_preparation import retained_bytes
import asyncio
from toad.widgets.presentation_window import (
    DirectionalPreparation, PreparationDemand, PresentationBudget,
)

from textual.widget import Widget
from textual.walk import walk_depth_first
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
    def body_ready(self) -> bool:
        raise NotImplementedError

    @property
    def body_requires_geometry(self) -> bool:
        raise NotImplementedError

    def retire_body(self) -> Coroutine[None, None, bool]:
        raise NotImplementedError

    async def restore_body(self) -> bool:
        raise NotImplementedError

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

    @property
    @abstractmethod
    def width(self) -> int: ...

    @property
    @abstractmethod
    def rows(self) -> int: ...

    @property
    @abstractmethod
    def widgets(self) -> int: ...

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

    async def prepare_publication(self, body):
        return self

    def paint_ready(self, body) -> bool:
        """A measured extent or mutable native tree is not captured paint."""
        return False

    def requires_geometry(self, body) -> bool:
        """Settled native content needs its box; retained extent does not."""
        return not self.dormant

    def publication_prepared(self, worker, paint):
        return self

    def measured(self, width, rows):
        return self

    def get_selection(self, body, selection, select_live):
        return select_live(selection)

    def publication_finished(self, body, worker):
        """A settled resource does not own this worker's publication."""
        return self

    def publication_failed(self, body, worker):
        """A replaced publication cannot invalidate another resource."""
        return self

    def released(self):
        return self

    def style_updated(self, body):
        return self

    def resized(self, size):
        return self

    async def retire(self, body):
        return False


@dataclass(frozen=True)
class MeasuredBody(BodyMeasurement):
    width: int = 0
    rows: int = 0
    widgets: int = 1

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


@dataclass(frozen=True)
class LiveBody(MeasuredBody):
    def prepare_publication(self, body):
        # Borrow the original published scene synchronously, before a writer
        # or its byte measurement can change the native tree.
        return body.capture_native_paint(self)

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
        return measure()

    def measured(self, width, rows):
        return self if (width, rows) == (self.width, self.rows) else replace(self, width=width, rows=rows)

    def render(self, body, crop, render_live):
        return render_live(crop)

    async def restore(self, body):
        return

    async def materialize(self, body):
        return

    def retire(self, body):
        return body.retire_native_body(self)


@dataclass(frozen=True, kw_only=True)
class MaterializingBody(BodyMeasurement):
    """One native writer borrowing the body's preceding paint resource.

    Dimensions and retained bytes belong to that resource. The worker owns
    publication and interaction; a pending writer is never a second extent.
    """

    previous: BodyMeasurement
    worker: Worker

    @property
    def width(self):
        return self.previous.width

    @property
    def rows(self):
        return self.previous.rows

    @property
    def widgets(self):
        return self.previous.widgets

    @property
    def dormant(self):
        return True

    def ready(self, body):
        return self.paint_ready(body)

    def paint_ready(self, body):
        return self.previous.paint_ready(body)

    def requires_geometry(self, body):
        # Pending work without preceding pixels still lays out native children.
        # Dormancy describes interaction, not that writer's layout demand.
        return not self.paint_ready(body)

    def publication_prepared(self, worker, paint):
        # A later writer may already own this body while joining our worker.
        # Update the resource in that original chain, never its writer identity.
        previous = (paint if self.worker is worker
                    else self.previous.publication_prepared(worker, paint))
        return self._updated(previous)

    def cost(self, body):
        return max(self.previous.cost(body), body.materialized_widget_count)

    @property
    def paint_bytes(self):
        return self.previous.paint_bytes

    def height(self, body, width, measure):
        return self.previous.height(body, width, measure)

    def render(self, body, crop, render_live):
        return self.previous.render(body, crop, render_live)

    def get_selection(self, body, selection, select_live):
        return self.previous.get_selection(body, selection, select_live) if self.ready(body) else None

    def _updated(self, previous):
        return self if previous is self.previous else replace(self, previous=previous)

    def measured(self, width, rows):
        return self._updated(self.previous.measured(width, rows))

    def invalidated(self):
        return self._updated(self.previous.invalidated())

    def released(self):
        return self._updated(self.previous.released())

    def style_updated(self, body):
        # Descendant writes belong to the new source, not the old captured
        # rows. Actual inherited paint/width changes still retire those rows.
        return self if self.paint_ready(body) else self.invalidated()

    def resized(self, size):
        return self._updated(self.previous.resized(size))

    async def restore(self, body):
        await self.before_publication()

    async def materialize(self, body):
        await self.before_publication()

    def before_publication(self) -> Awaitable[None]:
        # The next writer borrows only the worker, not a coroutine retaining
        # an old paint snapshot after the body's LRU has released it.
        return self.worker.wait()

    def publication_finished(self, body, worker):
        if self.worker is worker:
            if body._body_measurement is self:
                # Only the current writer exposes its newly committed native
                # tree. A newer writer still borrows the preceding pixels.
                body.refresh(layout=True)
                return LiveBody(self.width, self.rows, self.widgets)
            return self.previous
        return self._updated(self.previous.publication_finished(body, worker))

    def publication_failed(self, body, worker):
        if self.worker is worker:
            if body._body_measurement is self:
                return MeasuredBody(self.width, self.rows, self.widgets)
            return self.previous
        return self._updated(self.previous.publication_failed(body, worker))


@dataclass(frozen=True, kw_only=True)
class RenderedBody(MeasuredBody):
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
        return (self.paint_ready(body) and body.native_body_ready()
                and self.style_revision == body._subtree_style_revision)

    def paint_ready(self, body):
        # Captured strips are immutable. Loading and changes to the new native
        # descendants do not change them; inherited effective paint does.
        return (body.is_mounted and not body._closing
                and self.paint_state.style_key == body.styles._cache_key
                and self.paint_state.same_paint(body._resolved_paint_state()))

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

    def get_selection(self, body, selection, select_live):
        return (selection.extract(self.content.text), '\n') if self.paint_ready(body) else None

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
        self._body_viewport = None
        super().__init__(*args, **kwargs)

    @property
    def body_dormant(self):
        return self._body_measurement.dormant

    @property
    def body_ready(self):
        return self._body_measurement.ready(self)

    @property
    def body_requires_geometry(self):
        return self._body_measurement.requires_geometry(self)

    @property
    def is_container(self):
        # Rendered and pending resources paint their whole original subtree.
        # Native children remain in custody for the worker and interaction,
        # but must not overpaint the preceding rows while it is reconstructing.
        return not self._body_measurement.paint_ready(self) and super().is_container

    @property
    def _render_widget(self):
        return self if self._body_measurement.paint_ready(self) else super()._render_widget

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
        self._update_body_measurement(self._body_measurement.released())

    def invalidate_body(self):
        self._update_body_measurement(self._body_measurement.invalidated())

    def _update_body_measurement(self, measurement):
        if measurement is self._body_measurement:
            return
        self._body_measurement = measurement
        # The resource owns descendant participation and cover selection as
        # well as extent. Publish that change before any native prune awaits;
        # NodeList removal happens later and cannot invalidate it for us.
        self._invalidate_subtree_geometry()
        if self._body_viewport is not None:
            self._body_viewport.request()

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
        return self._body_measurement.get_selection(self, selection, super().get_selection)

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
        publication = AwaitComplete(previous.before_publication())
        paint = AwaitComplete(previous.prepare_publication(self))

        async def materialize():
            try:
                # Identity guards prevent an old commit; joining its actual
                # worker also prevents old native writes after the new commit.
                await publication
                [prepared] = await paint
                if prepared is not previous:
                    # A pending predecessor's unchanged resource is already
                    # in this chain, including capture/width/style updates
                    # made while we joined it. Only a new capture replaces it.
                    # Width is the body's content measurement. An offscreen
                    # widget's last committed outer size is not a new demand.
                    # Genuine measurement/resize hooks have already updated
                    # this original resource while byte preparation awaited.
                    if prepared.width != self._body_measurement.width:
                        prepared = prepared.invalidated()
                    self._update_body_measurement(self._body_measurement.publication_prepared(worker, prepared))
                await (self.materialize_native_body() if work is None else work())
                if self.is_attached:
                    self._update_body_measurement(
                        self._body_measurement.publication_finished(self, worker))
            except BaseException:
                self._update_body_measurement(
                    self._body_measurement.publication_failed(self, worker))
                raise

        worker = self.run_worker(materialize(), group="body-materialization", exit_on_error=False)
        current = MaterializingBody(previous=previous, worker=worker)
        self._update_body_measurement(current)
        self.refresh(layout=True)
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
        if not children:
            return BodyMeasurement.retire(current, self)
        paint = self.capture_native_paint(current)
        return self.finish_native_retirement(current, children, paint)

    def capture_native_paint(self, current):
        """Capture once for retirement and preceding-source publication."""
        if (not current.ready(self) or not self.is_attached or self.lock.is_locked
                or (self.screen.focused is not None
                    and self in self.screen.focused.walk_ancestors(with_self=True))
                or any(self in endpoint.walk_ancestors(with_self=True)
                       for endpoint in self.screen.selections)
                or any(not child.body_ready for child in walk_depth_first(self, with_root=False)
                       if isinstance(child, ViewportBody))):
            return BodyMeasurement.prepare_publication(
                MeasuredBody(current.width, current.rows, current.widgets), self)
        compositor = self.screen._compositor
        style_revision = self._subtree_style_revision
        paint_state = self._resolved_paint_state()
        captured = tuple(compositor.published_geometry((self,)))
        if not captured:
            return BodyMeasurement.prepare_publication(
                MeasuredBody(current.width, current.rows, current.widgets), self)
        _body, placement = captured[0]
        size, rows = compositor.render_subtree_strips(self, placement)
        # Native capture already owns final styled terminal rows. Retain those
        # rows directly; rendering them again in Rich workers duplicates work
        # and serializes a resource that never leaves this process.
        content = PreparedRichContent(size.width, tuple(rows))
        widgets = self.materialized_widget_count

        async def measured():
            size_bytes = await self.app.preparation.run_thread(retained_bytes, content)
            return RenderedBody(
                current.width, current.rows, widgets, content=content,
                resource_bytes=size_bytes, style_revision=style_revision, paint_state=paint_state,
            )

        return measured()

    async def finish_native_retirement(self, current, children, paint):
        rendered = await paint
        # The original state is the captured source/width/style lifetime. An
        # asynchronous change invalidates it rather than copying a revision.
        if self._body_measurement is not current or not self.is_attached or self._closing:
            return False
        if not rendered.ready(self):
            return False
        async with self.retirement_custody() as can_commit:
            if (not can_commit or self._body_measurement is not current or not rendered.ready(self)
                    or not self.is_attached or self._closing
                    or self._body_viewport is None
                    or self in self._body_viewport.protected()):
                return False
            self._update_body_measurement(rendered)
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
        measurement = self._body_measurement
        height = measurement.height(self, width, lambda: native_height(container, viewport, width))
        if self._body_measurement is measurement:
            # Extent measurement updates its current resource; it cannot
            # replace a pending worker or overwrite width invalidation.
            self._update_body_measurement(measurement.measured(width, height))
        return height

    def get_content_width(self, container, viewport):
        if self.body_dormant:
            return self._body_measurement.width
        return super().get_content_width(container, viewport)

    def on_unmount(self):
        if self._body_viewport is not None:
            self._body_viewport.discard(self)
            self._body_viewport = None
        self._update_body_measurement(LiveBody())

    def on_mount(self):
        from toad.screens.workspace import WorkspaceScreen
        from toad.widgets.history_anchor import HistoryWindow
        if isinstance(self.screen, WorkspaceScreen):
            for ancestor in self.walk_ancestors():
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
        windows = tuple(self.frame_windows())
        return tuple(dict.fromkeys((
            *(target for window in windows if window in self.anchors
              for target in window.history_geometry_targets()),
            *(target for window in windows
              for target in window.document_viewport.geometry_targets()),
        )))

    def visible_bodies(self, windows):
        """Select paint bodies once from the original scene and native owner.

        Nested windows own their own bodies. An enclosing window must not
        acquire their readiness or schedule their reconstruction as its work.
        This cohort is synchronous; it is not another membership registry.
        """
        from toad.widgets.history_anchor import HistoryWindow

        windows = set(windows)
        for body in self.screen._compositor.visible_widgets:
            if isinstance(body, ViewportBody):
                for ancestor in body.walk_ancestors():
                    if isinstance(ancestor, HistoryWindow):
                        if ancestor in windows:
                            yield ancestor, body
                        break

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
        for window, body in self.visible_bodies(windows):
            if not body.body_ready:
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

    def displayed(self) -> bool:
        """Native ancestry owns visibility, including a window mounted late.

        Hydration can finish after its logical session is hidden. Its newly
        registered window cannot participate in that screen's frame merely
        because no viewport suspension preceded its construction.
        """
        window = self.window()
        return (self.presentation.screen.is_current
                and all(node.display for node in window.walk_ancestors(with_self=True)))

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
        return not self._suspended and self.membership.displayed()

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
        return tuple(owner for owner in self.owners if owner.body_requires_geometry)

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
        if not self.accepts_frame() or not self.window.is_attached or self.window._closing:
            return
        self._pending = True
        if not self._running:
            self._running = True
            self._worker = self.window.run_worker(partial(self._reconcile), group="viewport-bodies")

    def scroll_changed(self, *_args) -> None:
        # Native scroll is the demand producer. Screen-wide layout (including
        # this working set's own pruning) is not another scroll or admission.
        if (not self.accepts_frame() or not self.window.is_attached
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
            for node in endpoint.walk_ancestors(with_self=True):
                if not isinstance(node, Widget) or node is self.window:
                    break
                protected.add(node)
        if self.window.history_anchor is not None:
            protected.add(self.window.history_anchor.widget)
        return protected

    @property
    def visible_bodies_ready(self) -> bool:
        # Frame admission and source preparation ask the same native owner.
        # A nested body still contributes even when its outer fragment owns
        # retirement; a nested window contributes to its own viewport only.
        window = self.window
        return all(body.body_ready for _window, body in
                   window.screen.viewport_presentation.visible_bodies((window,)))

    async def _reconcile(self) -> None:
        try:
            while (self._pending and self.accepts_frame()
                   and self.window.is_attached and not self.window._closing):
                self._pending = False
                screen = self.window.screen
                visible = screen._compositor.visible_widgets
                protected = self.protected()
                owners = tuple(self.body_roots())
                required = tuple(owner for owner in owners if owner in visible or owner in protected)
                # Reuse the same body admission and worker. Restore only the
                # neighboring destination bodies, not every skipped record.
                demand = self.lookahead.demand
                ahead_owners = []
                visible_indexes = [index for index, node in enumerate(owners) if node in visible]
                if visible_indexes:
                    count = self.lookahead.admission(self.budget, self.window.size.height)
                    runway = self.budget.runway(
                        owners, min(visible_indexes), max(visible_indexes) + 1,
                        self.window.size.height,
                    )
                    predicted = demand.neighbors(
                        owners, min(visible_indexes), max(visible_indexes) + 1, count,
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
        if (not self.window.is_attached or not self.accepts_frame()
                or not self.lookahead.accepts(demand)):
            return ()
        owners = tuple(owner for owner in owners if owner.is_attached and not owner._closing)
        async with AsyncExitStack() as mutation:
            if any(not owner.body_ready for owner in owners):
                await mutation.enter_async_context(self.window.preserve_reader(anchor))
            # Each original materialization worker acquires its prepared result
            # once. Source-page lookahead warms unmounted leaves separately;
            # repeating that work here delays every body before delivery begins.
            # Join this admitted cohort together under the same reader anchor,
            # retaining the runtime's existing worker and resource limits.
            async with asyncio.TaskGroup() as restoration:
                tasks = []
                for owner in owners:
                    if not self.accepts_frame() or not self.lookahead.accepts(demand):
                        break
                    if owner.is_attached and not owner._closing:
                        tasks.append((owner, restoration.create_task(owner.restore_body())))
            restored = tuple(owner for owner, task in tasks if task.result())
        if restored:
            # Native child composition and nested page publication produce
            # readiness. The same frame owns capture after compensated layout.
            self.window.screen.frame_presentation.defer(self.window, self.request)
        return restored
