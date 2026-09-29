"""One frame lifetime owns writer receipts, readiness and deferred source work."""
from __future__ import annotations

import asyncio
import sys
from abc import abstractmethod
from functools import partial
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from agent_comms.mro_dispatch import MroDispatch, handles
from textual.driver import Driver
from textual.widget import Widget
from toad.screens.workspace import WorkspaceScreen


class FrameFlush(DeclaredFamily, affix="Flush"):
    driver_type: type[Driver]

    def __init__(self, driver):
        self.driver = driver

    @classmethod
    def for_driver(cls, driver):
        declarations = {kind.driver_type: kind for kind in cls.members_with(cls)}
        return next(declarations[ancestor](driver) for ancestor in type(driver).__mro__ if ancestor in declarations)

    @abstractmethod
    def submit(self, callback): ...


class SynchronousFrameFlush(FrameFlush):
    driver_type = Driver

    def submit(self, callback):
        callback()


if sys.platform != "win32":
    # The framework's POSIX driver imports termios; its declaration exists only
    # at that external platform boundary, like Textual's own driver selection.
    from textual.drivers.linux_driver import LinuxDriver

    class TerminalFrameFlush(FrameFlush):
        driver_type = LinuxDriver

        def submit(self, callback):
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
        frame.state = SuspendedFrame()

    def resume(self, frame):
        pass


class PendingFrame(FrameState):
    def displayed(self, frame):
        receipt = WritingFrame()
        frame.state = receipt
        FrameFlush.for_driver(frame.screen.app._driver).submit(partial(frame.written, receipt))


class WritingFrame(FrameState):
    pass


class SuspendedFrame(FrameState):
    def resume(self, frame):
        self.begin(frame)


class PresentedFrame(FrameState):
    ready = True

    def defer(self, frame, owner, callback):
        if frame.screen.app._atomic_mode_switch:
            super().defer(frame, owner, callback)
        else:
            owner.call_after_refresh(callback)


class ClosedFrame(FrameState):
    def defer(self, frame, owner, callback):
        pass

    def begin(self, frame):
        pass

    def suspend(self, frame):
        pass


class FramePresentation:
    def __init__(self, screen):
        self._screen = ref(screen)
        self.state: FrameState = PendingFrame()
        self.callbacks: dict[tuple[Widget, object], None] = {}
        self.presented = asyncio.Event()

    @property
    def screen(self):
        screen = self._screen()
        if screen is None:
            raise ReferenceError("Frame screen has retired")
        return screen

    @property
    def ready(self):
        return self.state.ready

    def begin(self):
        self.state.begin(self)

    def defer(self, owner, callback):
        self.state.defer(self, owner, callback)

    def displayed(self):
        self.state.displayed(self)

    def written(self, receipt: WritingFrame):
        if receipt is not self.state:
            return
        self.state = PresentedFrame()
        self.presented.set()
        callbacks = tuple(self.callbacks)
        self.callbacks.clear()
        for owner, callback in callbacks:
            if owner.is_attached:
                # The existing message pump rejects work once its owner closes.
                owner.call_later(callback)

    def suspend(self):
        self.state.suspend(self)
        self.presented.set()

    def resume(self):
        self.state.resume(self)

    def close(self):
        self.state = ClosedFrame()
        self.callbacks.clear()
        self.presented.set()

    async def wait(self):
        await self.presented.wait()
        screen = self.screen
        return self.ready and screen.is_attached and screen.is_current


class FrameDisplay(MroDispatch):
    @handles(WorkspaceScreen)
    def workspace(self, screen):
        screen.frame_presentation.displayed()
