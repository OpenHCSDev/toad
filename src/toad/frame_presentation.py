"""Each frame tracks terminal flush completion, readiness and deferred source work."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from weakref import ref
from typing import TYPE_CHECKING, ClassVar

from agent_comms.declared_family import DeclaredFamily
from textual._paint_state import PaintLayer, PaintState
from textual.color import Color, TRANSPARENT
from ui_theme.scheme import ThemeColour
from textual.app import ScreenStackError, UnknownModeError
from textual.widget import Widget
from textual.strip import Strip
from ui_theme.clock import Animation
from ui_theme.effects import Effect, Fade, Frame, Mix

if TYPE_CHECKING:
    from toad.screens.workspace import WorkspaceScreen


class ToneLayer(PaintLayer):
    """A widget's own CSS paint laid over its area tone.

    CSS backgrounds (hover, selection, transparency) compose over the tone by
    alpha; with no tone the CSS paint is unchanged.
    """

    __slots__ = ("styles", "paint_background", "paint_foreground", "auto_color", "layer_opacity", "text_style", "background_tint")

    def __init__(self, styles, tone: Color | None, opacity: float, paint) -> None:
        self.styles = styles
        self.layer_opacity = styles.layer_opacity * opacity
        stated = paint.paint_background
        if stated is None:
            stated = styles.paint_background
        foreground = paint.paint_foreground
        self.paint_foreground = styles.paint_foreground if foreground is None else foreground
        self.auto_color = styles.auto_color if foreground is None else foreground.auto
        text_style = paint.text_style
        self.text_style = styles.text_style if text_style is None else text_style
        tint = paint.background_tint
        self.background_tint = styles.background_tint if tint is None else tint
        self.paint_background = stated if tone is None else tone if stated is None else tone + stated
    text_opacity = property(lambda self: self.styles.text_opacity)


class TonePaint:
    """Paints a screen area on its declared theme tone; ``None`` keeps the parent's."""

    tone: ClassVar[type[ThemeColour] | None]
    paint_background = paint_foreground = text_style = background_tint = None
    paint_opacity = 1.0

    @property
    def paint_layer(self) -> PaintLayer:
        tone = self.tone
        return ToneLayer(self.styles, None if tone is None else self.app.colours.colour(tone),
                         self.paint_opacity, self)


class UntintedTonePaint(TonePaint):
    """Keep the parent's area tone without an additional focus tint."""

    tone = None
    background_tint = TRANSPARENT


class AlternatingTonePaint(TonePaint):
    """A row of a list: every other row, by its laid-out position, steps onto ``alternate_tone``."""

    alternate_tone: ClassVar[type[ThemeColour]]

    @property
    def tone(self) -> type[ThemeColour] | None:
        region = self.virtual_region
        return self.alternate_tone if region.height and region.y // region.height % 2 else None


class FrameState(DeclaredFamily, affix="Frame"):
    ready = False

    @property
    def scene(self):
        return self

    def displayed(self, frame):
        writing = WritingFrame(self.scene)
        frame.state = writing
        frame.screen.app._driver.call_after_flush(partial(frame.written, writing))

    def defer(self, frame, owner, callback):
        frame.callbacks[owner, callback] = None
        owner.call_after_refresh(frame.flush_owner, owner, callback)

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

    def resume(self, frame):
        self.previous.restore(frame)

    def suspend(self, frame):
        pass

    def displayed(self, frame):
        pass


class PresentedFrame(FrameState):
    ready = True

    def __init__(self, scene: PendingFrame):
        self._scene = scene

    @property
    def scene(self):
        return self._scene

    def restore(self, frame):
        frame.present()

    def displayed(self, frame):
        pass


class ClosedFrame(FrameState):
    def displayed(self, frame):
        pass

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

    def awaits_publication(self, owner: Widget, callback: Callable[[], object]) -> bool:
        """Whether this owner's callback already waits for its frame to be written."""
        return (owner, callback) in self.callbacks

    def defer(self, owner: Widget, callback: Callable[[], object]) -> None:
        if not self.awaits_publication(owner, callback):
            self.state.defer(self, owner, callback)

    def flush_owner(self, owner: Widget, callback: Callable[[], object]) -> None:
        """Wait for the sender's frame before waiting for the terminal writer."""
        if self.awaits_publication(owner, callback):
            self.screen.app._driver.call_after_flush(
                partial(self.release, owner, callback, self.state.scene))

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


class Animated[FrameT: Frame](Widget):
    """A native widget whose effect uses the app clock and published visibility."""

    text_fades: ClassVar[tuple[Fade, ...]] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.effects: dict[Effect, Animation] = {}
        self.wanted: set[Effect] = set()

    def run_effect(self, effect: Effect) -> None:
        self.stop_effect(effect)
        if not effect.finite:
            self.wanted.add(effect)
        if self.is_on_screen:
            self.effects[effect] = self.app.colours.clock.start(effect, self)

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

    def effect_running(self, effect: Effect[FrameT]) -> bool:
        animation = self.effects.get(effect)
        return animation is not None and not animation.finished

    def on_unmount(self) -> None:
        self.stop_effect()

    def on_hide(self) -> None:
        for effect in tuple(self.effects):
            self.effects.pop(effect).stop()
        self.refresh()

    def on_show(self) -> None:
        for effect in self.wanted:
            if effect not in self.effects:
                self.effects[effect] = self.app.colours.clock.start(effect, self)
        self.refresh()

    def paint_effects(self, strip: Strip, *frames: Mix) -> Strip:
        for frame in (*frames, *(self.effect_frame(effect) for effect in self.text_fades)):
            strip = self.app.colours.paint_rising(frame, strip)
        return strip

    def render_line(self, y: int, paint: PaintState) -> Strip:
        return self.paint_effects(super().render_line(y, paint))

    @property
    def animation_visible(self) -> bool:
        if not self.is_attached or not self.app.app_focus:
            return False
        screen = self.screen
        try:
            current = self.app.screen
        except (ScreenStackError, UnknownModeError):
            return False
        return screen is current and self in screen._compositor.visible_widgets

    def repaint(self) -> None:
        self.refresh()
