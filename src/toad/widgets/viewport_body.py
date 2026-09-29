"""Viewport-owned lifetimes for reconstructible document presentation.

The document keeps its source and native measured extent. Descendant widgets,
their message pumps, subscriptions and render caches have a shorter lifetime.
The window owns admission; documents implement their own retirement/restoration.
"""

from collections import OrderedDict
from weakref import WeakSet, ref

from textual.widget import Widget


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

    def prepare(self, wait_for_bodies: bool) -> bool:
        screen = self.screen
        if not screen.is_current:
            return True
        if wait_for_bodies:
            for window in self.windows:
                if not window.document_viewport.visible_bodies_ready:
                    window.document_viewport.request()
                    screen._repaint_required = True
                    return False
        changed = False
        for window in self.windows:
            changed |= window.check_follow()
        if changed:
            screen._refresh_layout(scroll=True)
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

    DEFAULT_WARM_BODIES = 8
    """Initial working-set budget; callers may tune it, including zero."""

    def __init__(self, window, *, max_warm_bodies: int = DEFAULT_WARM_BODIES):
        if type(max_warm_bodies) is not int or max_warm_bodies < 0:
            raise ValueError("max_warm_bodies must be a non-negative integer")
        self.max_warm_bodies = max_warm_bodies
        self._window = ref(window)
        self.owners = WeakSet()
        self._warm = OrderedDict()
        self._pending = False
        self._running = False
        window.watch(window, "scroll_y", self.request, init=False)
        window.screen.screen_layout_refresh_signal.subscribe(window, self.request)
        self.membership = WindowMembership(window)

    @property
    def window(self):
        window = self._window()
        if window is None:
            raise ReferenceError("The document viewport's window has been retired")
        return window

    def register(self, owner: ViewportBody) -> None:
        self.owners.add(owner)
        self._warm[ref(owner)] = None
        self.request()

    def discard(self, owner: ViewportBody) -> None:
        self.owners.discard(owner)
        self._warm.pop(ref(owner), None)

    def request(self, *_args) -> None:
        if not self.window.is_attached or self.window._closing:
            return
        self._pending = True
        if not self._running:
            self._running = True
            self.window.run_worker(self._reconcile(), group="viewport-bodies")

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
        visible = self.window.screen._compositor.visible_widgets
        return all(owner.body_ready for owner in self.owners if owner in visible)

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
                        self._warm[key] = None
                        self._warm.move_to_end(key)
                while len(self._warm) > self.max_warm_bodies:
                    self._warm.popitem(last=False)
                warm = {key() for key in self._warm} if active else set()
                retained = protected | warm | visible.keys()
                # Restore visible source before retiring unrelated bodies.
                ordered = sorted(owners, key=lambda owner: owner not in visible)
                for owner in ordered:
                    if not owner.is_attached or owner._closing:
                        continue
                    wanted = owner in retained
                    if owner.body_dormant and wanted:
                        async with self.window.history_lock:
                            if not self.window.is_attached or not owner.is_attached:
                                continue
                            if screen.is_current:
                                if not owner.body_measurement_stale:
                                    await owner.restore_body()
                                else:
                                    anchor = next((item for item in owners if item in visible and item.is_attached), owner)
                                    async with self.window.preserve_history(anchor):
                                        await owner.restore_body()
                            else:
                                continue
                    if (not wanted and not owner.body_dormant and owner not in self.protected()
                            and not (screen.is_current and owner in screen._compositor.visible_widgets)):
                        await owner.retire_body()
        finally:
            self._running = False
