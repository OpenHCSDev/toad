"""One frame lifetime owns writer receipts, readiness and deferred source work."""
from __future__ import annotations

import asyncio
import sys
from abc import abstractmethod
from collections.abc import Callable
from functools import partial
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from agent_comms.mro_dispatch import MroDispatch, handles
from textual.driver import Driver
from textual.widget import Widget
from toad.screens.workspace import WorkspaceScreen


class FrameFlush(DeclaredFamily, affix="Flush"):
    driver_type: type[Driver]

    def __init__(self, driver: Driver):
        self.driver = driver

    @classmethod
    def for_driver(cls, driver: Driver) -> FrameFlush:
        declarations = {kind.driver_type: kind for kind in cls.members_with(cls)}
        return next(declarations[ancestor](driver) for ancestor in type(driver).__mro__ if ancestor in declarations)

    @abstractmethod
    def submit(self, callback: Callable[[], None]) -> None: ...


class SynchronousFrameFlush(FrameFlush):
    driver_type = Driver

    def submit(self, callback: Callable[[], None]) -> None:
        callback()


if sys.platform != "win32":
    # The framework's POSIX driver imports termios; its declaration exists only
    # at that external platform boundary, like Textual's own driver selection.
    from textual.drivers.linux_driver import LinuxDriver

    class TerminalFrameFlush(FrameFlush):
        driver_type = LinuxDriver

        def submit(self, callback: Callable[[], None]) -> None:
            loop = asyncio.get_running_loop()

            def written():
                try:
                    loop.call_soon_threadsafe(callback)
                except RuntimeError:
                    pass  # The application loop closed after its terminal write.

            self.driver.call_after_flush(written)


class FrameState(DeclaredFamily, affix="Frame"):
    ready = False

    def displayed(self, frame):
        pass

    def defer(self, frame, owner, callback):
        frame.callbacks[owner, callback] = None

    def begin(self, frame):
        frame.state = PendingFrame()
        frame.presented.clear()

    def suspend(self, frame):
        frame.state = SuspendedFrame(self)

    def resume(self, frame):
        pass

    def restore(self, frame):
        self.begin(frame)
        frame.screen.refresh()


class PendingFrame(FrameState):
    def displayed(self, frame):
        receipt = WritingFrame()
        frame.state = receipt
        FrameFlush.for_driver(frame.screen.app._driver).submit(partial(frame.written, receipt))


class WritingFrame(FrameState):
    pass


class SuspendedFrame(FrameState):
    def __init__(self, previous: FrameState):
        self.previous = previous

    def resume(self, frame):
        self.previous.restore(frame)

    def suspend(self, frame):
        pass


class PresentedFrame(FrameState):
    ready = True

    def restore(self, frame):
        frame.present()

    def defer(self, frame, owner, callback):
        super().defer(frame, owner, callback)
        owner.call_after_refresh(frame.release, owner, callback)


class ClosedFrame(FrameState):
    def defer(self, frame, owner, callback):
        pass

    def begin(self, frame):
        pass

    def suspend(self, frame):
        pass


class FramePresentation:
    def __init__(self, screen: WorkspaceScreen):
        self._screen = ref(screen)
        self.state: FrameState = PendingFrame()
        self.callbacks: dict[tuple[Widget, Callable[[], object]], None] = {}
        self.presented = asyncio.Event()

    @property
    def screen(self) -> WorkspaceScreen:
        screen = self._screen()
        if screen is None:
            raise ReferenceError("Frame screen has retired")
        return screen

    @property
    def ready(self) -> bool:
        return self.state.ready

    def begin(self):
        self.state.begin(self)

    def defer(self, owner: Widget, callback: Callable[[], object]) -> None:
        if (owner, callback) not in self.callbacks:
            self.state.defer(self, owner, callback)

    def release(self, owner: Widget, callback: Callable[[], object]) -> None:
        """Release one owned operation only from a presented scene.

        An earlier after-refresh callback may arrive after this scene began
        another publication. Keep its work for that publication's writer
        receipt; closing removes the resource before either callback arrives.
        """
        from toad.screens.session_view import SessionView

        key = owner, callback
        if not self.ready or not self.screen.is_current or key not in self.callbacks:
            return
        if not owner.is_attached:
            del self.callbacks[key]
            return
        for source in owner.walk_ancestors(with_self=True):
            if isinstance(source, SessionView):
                if not source.is_current:
                    # Hidden mounts cannot borrow the departing frame. Their
                    # selected publication releases this same operation.
                    return
                break
        del self.callbacks[key]
        # The original message pump rejects work once its owner closes.
        owner.call_later(callback)

    def displayed(self):
        self.state.displayed(self)

    def written(self, receipt: WritingFrame) -> None:
        if receipt is not self.state:
            return
        self.present()

    def present(self) -> None:
        """A written or restored scene releases its same deferred source work."""
        self.state = PresentedFrame()
        self.presented.set()
        for owner, callback in tuple(self.callbacks):
            self.release(owner, callback)

    def suspend(self):
        self.state.suspend(self)
        self.presented.set()

    def resume(self):
        self.state.resume(self)

    def close(self):
        self.state = ClosedFrame()
        self.callbacks.clear()
        self.presented.set()

    async def wait(self) -> bool:
        await self.presented.wait()
        screen = self.screen
        return self.ready and screen.is_attached and screen.is_current


class FrameDisplay(MroDispatch):
    @handles(WorkspaceScreen)
    def workspace(self, screen):
        screen.frame_presentation.displayed()
