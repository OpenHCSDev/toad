"""Each frame tracks terminal flush completion, readiness and deferred source work."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, ClassVar
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from textual._paint_state import PaintState
from textual.app import ScreenStackError, UnknownModeError
from textual.strip import Strip
from textual.widget import Widget
from ui_theme.clock import Animation
from ui_theme.effects import Effect, Fade, Frame, Mix
from ui_theme.scheme import BackgroundColour

from toad.tone_paint import TonePaint

if TYPE_CHECKING:
    from toad.screens.workspace import WorkspaceFrame
    from toad.widgets.transcript_history import LineHistory, TranscriptPageView


class FrameState(DeclaredFamily, affix="Frame"):
    ready = False

    @property
    def scene(self):
        return self

    def displayed(self, frame):
        writing = WritingFrame(self.scene)
        frame.state = writing
        frame.screen.app._driver.call_after_flush(partial(frame.written, writing))

    def defer[Result](self, frame: FramePresentation, owner: Widget, callback: Callable[[], Result]):
        frame.callbacks[owner, callback] = None
        owner.call_after_refresh(frame.flush_owner, owner, callback)

    def begin(self, frame: FramePresentation):
        frame.state = PendingFrame()
        frame.presented.clear()

    def suspend(self, frame: FramePresentation):
        frame.state = SuspendedFrame(self)

    def resume(self, frame: FramePresentation):
        pass

    def restore(self, frame: FramePresentation):
        self.begin(frame)
        frame.screen.refresh()


class PendingFrame(FrameState):
    pass


class WritingFrame(FrameState):
    def __init__(self, scene: PendingFrame):
        self._scene = scene

    @property
    def scene(self):
        return self._scene


class SuspendedFrame(FrameState):
    def __init__(self, previous: FrameState):
        self.previous = previous

    @property
    def scene(self):
        return self.previous.scene

    def resume(self, frame: FramePresentation):
        self.previous.restore(frame)

    def suspend(self, frame: FramePresentation):
        pass

    def displayed(self, frame: FramePresentation):
        pass


class PresentedFrame(FrameState):
    ready = True

    def __init__(self, scene: PendingFrame):
        self._scene = scene

    @property
    def scene(self):
        return self._scene

    def restore(self, frame: FramePresentation):
        frame.present()

    def displayed(self, frame: FramePresentation):
        pass


class ClosedFrame(FrameState):
    def displayed(self, frame: FramePresentation):
        pass

    def defer[Result](self, frame: FramePresentation, owner: Widget, callback: Callable[[], Result]):
        pass

    def begin(self, frame: FramePresentation):
        pass

    def suspend(self, frame: FramePresentation):
        pass


class FramePresentation:
    def __init__(self, screen: WorkspaceFrame):
        self._screen = ref(screen)
        self.state: FrameState = PendingFrame()
        self.callbacks: dict[tuple[Widget, Callable[[], object]], None] = {}
        self.presented = asyncio.Event()

    @property
    def screen(self) -> WorkspaceFrame:
        screen = self._screen()
        if screen is None:
            raise ReferenceError("Frame screen has retired")
        return screen

    @property
    def ready(self) -> bool:
        return self.state.ready

    def begin(self):
        self.state.begin(self)

    def awaits_publication(self, owner: Widget, callback: Callable[[], object]) -> bool:
        """Whether this owner's callback already waits for its frame to be written."""
        return (owner, callback) in self.callbacks

    def defer(self, owner: Widget, callback: Callable[[], object]) -> None:
        if not self.awaits_publication(owner, callback):
            self.state.defer(self, owner, callback)

    def flush_owner(self, owner: Widget, callback: Callable[[], object]) -> None:
        """Wait for the sender's frame before waiting for the terminal writer."""
        if self.awaits_publication(owner, callback):
            self.screen.app._driver.call_after_flush(partial(self.release, owner, callback, self.state.scene))

    def release(self, owner: Widget, callback: Callable[[], object], scene: PendingFrame) -> None:
        """Release the admitted owner after its publication's writer join."""
        key = owner, callback
        if key not in self.callbacks:
            return
        if owner.is_attached:
            if scene is not self.state.scene:
                owner.call_after_refresh(self.flush_owner, owner, callback)
                return
            if not self.screen.release_frame_callback(owner, callback):
                return
        del self.callbacks[key]

    def displayed(self):
        self.state.displayed(self)

    def written(self, writing: WritingFrame) -> None:
        if writing is not self.state:
            return
        self.present()

    def present(self) -> None:
        """A written or restored scene releases its same deferred source work."""
        self.state = PresentedFrame(self.state.scene)
        self.presented.set()
        for owner, callback in tuple(self.callbacks):
            if owner.is_attached:
                owner.call_after_refresh(self.flush_owner, owner, callback)

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


class EffectPhase:
    """A running effect; its subclasses are the effect not yet started and finished."""

    # Whether the effect is moving now.
    in_motion: ClassVar[bool] = True

    def paint(self, owner: AnimationEffects[Mix], effect: Effect[Mix], strip: Strip):
        return owner.paint_effects(strip, owner.effect_frame(effect))

    def keeps_arrivals[Item](self, arrivals: Iterable[Item]) -> Iterable[Item]:
        return arrivals

    def on_new_arrival(self, owner: LineHistory, effect: Effect[Mix], pages: deque[TranscriptPageView]):
        """Arrivals during a running burst join its fade and reveal."""


class EffectUnstarted(EffectPhase):
    in_motion = False

    def paint(self, owner: AnimationEffects[Mix], effect: Effect[Mix], strip: Strip):
        owner.run_effect(effect)
        return super().paint(owner, effect, strip)

    def on_new_arrival(self, owner: LineHistory, effect: Effect[Mix], pages: deque[TranscriptPageView]):
        owner.arrivals_began()


class EffectFinished(EffectPhase):
    in_motion = False

    def keeps_arrivals[Item](self, arrivals: Iterable[Item]) -> Iterable[Item]:
        return ()

    def on_new_arrival(self, owner: LineHistory, effect: Effect[Mix], pages: deque[TranscriptPageView]):
        for page in pages:
            page.arrivals.clear()
        owner.stop_effect(effect)
        owner.arrivals_began()


EFFECT_UNSTARTED, EFFECT_RUNNING, EFFECT_FINISHED = EffectUnstarted(), EffectPhase(), EffectFinished()


class AnimationEffects[FrameT: Frame](TonePaint):
    """A native widget whose effect uses the app clock and published visibility."""

    text_fades: ClassVar[tuple[Fade, ...]] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.effects: dict[Effect, Animation] = {}
        self.wanted: set[Effect] = set()

    def run_effect(self, effect: Effect) -> None:
        # An effect requested before the widget shows (on mount) starts when it does.
        self.stop_effect(effect)
        self.wanted.add(effect)
        if self.is_on_screen:
            self.start_wanted()

    def start_wanted(self) -> None:
        # A finite effect plays once; a continuous one resumes each time the widget shows.
        for effect in tuple(self.wanted):
            if effect not in self.effects:
                self.effects[effect] = self.app.colours.clock.start(effect, self)
                if effect.finite:
                    self.wanted.discard(effect)

    def stop_effect(self, *effects: Effect) -> None:
        if effects:
            self.wanted.difference_update(effects)
        else:
            self.wanted.clear()
        for effect in effects or tuple(self.effects):
            if animation := self.effects.pop(effect, None):
                animation.stop()

    def effect_frame(self, effect: Effect[FrameT]) -> FrameT:
        animation = self.effects.get(effect)
        return effect.final if animation is None else animation.frame()

    def effect_phase(self, effect: Effect[FrameT]) -> EffectPhase:
        animation = self.effects.get(effect)
        return EFFECT_UNSTARTED if animation is None else EFFECT_FINISHED if animation.finished else EFFECT_RUNNING

    async def on_unmount(self) -> None:
        self.stop_effect()

    def on_hide(self) -> None:
        for effect in tuple(self.effects):
            self.effects.pop(effect).stop()
        self.refresh()

    def on_show(self) -> None:
        self.start_wanted()
        self.refresh()

    def paint_effects(self, strip: Strip, *frames: Mix) -> Strip:
        # Background-origin text rises from the widget's tone; accent flashes
        # keep their declared origin. Both finish at each run's own ink.
        for frame in (
            *frames,
            *(
                (
                    replace(self.effect_frame(effect), start=self.text_background)
                    if effect.start is BackgroundColour
                    else self.effect_frame(effect)
                )
                for effect in self.text_fades
            ),
        ):
            strip = self.app.colours.paint_rising(frame, strip)
        return strip

    @property
    def animation_visible(self) -> bool:
        if not self.is_attached or not self.app.app_focus:
            return False
        screen = self.screen
        try:
            current = self.app.screen
        except ScreenStackError, UnknownModeError:
            return False
        return screen is current and self in screen._compositor.visible_widgets

    def repaint(self) -> None:
        self.refresh()


class Animated[FrameT: Frame](AnimationEffects[FrameT], Widget):
    """A widget whose own rendered rows receive its declared text fades."""

    def render_line(self, y: int, paint: PaintState) -> Strip:
        return self.paint_effects(super().render_line(y, paint))
