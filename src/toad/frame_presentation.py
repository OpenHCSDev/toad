"""Each frame tracks terminal flush completion, readiness and deferred source work."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from functools import cached_property, partial
from typing import TYPE_CHECKING, ClassVar
from weakref import WeakSet, ref

from agent_comms.nominal.declared_family import DeclaredFamily
from textual._paint_state import PaintState
from textual.app import ScreenStackError, UnknownModeError
from textual import events
from textual.strip import Strip
from textual.widget import Widget
from ui_theme.clock import Animation
from ui_theme.effects import NEW_TEXT, Effect, Fade, Frame, Mix, TextFade
from ui_theme.scheme import BackgroundColour, ThemeColour

from toad.tone_paint import TonePaint
from textual import on

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


@dataclass(frozen=True)
class Cascade(TextFade):
    """One fade played row after row: each row starts `position * span` later.

    A burst of rows comes in progressively, top to bottom, instead of rising as
    one block. Row 0 is the plain fade; a row whose start has not come yet is
    still the fade's first frame, the background, so it is not yet visible.
    """

    fade: Fade
    span: float

    @property
    def duration(self) -> float:  # type: ignore[override]
        return self.fade.duration + self.span

    @property
    def frames_per_second(self) -> float:  # type: ignore[override]
        return self.fade.frames_per_second

    @property
    def start(self) -> type[ThemeColour]:  # type: ignore[override]
        """Its fade's: re-timing a fade row by row does not change what it rises from."""
        return self.fade.start

    def frame(self, elapsed: float) -> Mix:
        return self.fade.frame(elapsed)

    def began(self, position: float) -> float:
        """When the row `position` (0 first, 1 last) of the way through starts to rise."""
        return position * self.span

    def at(self, elapsed: float, position: float) -> Mix:
        """The frame of a row `position` (0 first, 1 last) of the way through the cascade."""
        return self.fade.frame(elapsed - self.began(position))

    def front(self, elapsed: float) -> float:
        """How far through the cascade the risen front stands, 0 to 1.

        A row is risen when its own fade has finished, which is `fade.duration` after
        that row began. Reading the front off the start of each row instead would put
        it at 1 while the last rows were still mid-fade, which is a second clock for
        one animation: the paint would still be running and a following tail would
        already sit at the bottom.
        """
        return min(1.0, max(0.0, (elapsed - self.fade.duration) / self.span)) if self.span else 1.0

    def unrisen(self, elapsed: float, rows: int) -> int:
        """How many of `rows` have not risen yet: they are still below what the reader reads."""
        if rows < 2:
            return 0
        return max(0, rows - 1 - int(self.front(elapsed) * (rows - 1)))

    @property
    def final(self) -> Mix:
        return self.fade.final


# Arriving transcript rows: the new-text fade, started row after row across 0.4 s.
ARRIVAL = Cascade(NEW_TEXT, span=0.4)


class EffectPhase:
    """Where an effect is: running, not yet started or finished. Only a running one moves."""

    # Whether the effect is moving now.
    in_motion: ClassVar[bool] = False

    def shown[Shown: Frame](self, effect: Effect[Shown], visible: bool,
                            position: float = 0.0) -> Shown:
        return effect.final

    def now(self) -> EffectPhase:
        return self

    def stop(self) -> None:
        """Nothing runs, so nothing stops."""

    def paint(self, owner: AnimationEffects[Mix], effect: Effect[Mix], strip: Strip,
              position: float = 0.0):
        """One row of `owner`, at its place through what the effect plays across: the frame
        comes from the phase, so a finished, invisible or row-after-row effect all answer
        in one body (`shown`)."""
        return owner.paint_effects(strip, owner.effect_frame(effect, position))

    def unrevealed(self, effect: Cascade, rows: int) -> int:
        """Rows of a cascade still waiting to rise; only a running one holds any back."""
        return 0

    def keeps_arrivals[Item](self, arrivals: Iterable[Item]) -> Iterable[Item]:
        return arrivals

    def on_new_arrival(self, owner: LineHistory, effect: Effect[Mix], pages: deque[TranscriptPageView]):
        """Arrivals during a running burst join its fade and reveal."""


@dataclass(frozen=True)
class EffectRunning(EffectPhase):
    animation: Animation
    in_motion = True

    def shown[Shown: Frame](self, effect: Effect[Shown], visible: bool,
                            position: float = 0.0) -> Shown:
        # The clock ticks only animation-visible targets, but an unfocused app or a
        # covered screen still paints them: a frame frozen at the effect's start would
        # leave an arrival's revealed rows blank and its fade at the background colour.
        # Through the animation, which owns the phase time a continuous effect reads from
        # the clock: the effect alone cannot answer for one.
        return self.animation.at(position) if visible else effect.final

    def now(self) -> EffectPhase:
        return EFFECT_FINISHED if self.animation.finished else self

    def unrevealed(self, effect: Cascade, rows: int) -> int:
        animation = self.animation
        return 0 if animation.finished else effect.unrisen(animation.elapsed, rows)

    def stop(self) -> None:
        self.animation.stop()


class EffectUnstarted(EffectPhase):
    def paint(self, owner: AnimationEffects[Mix], effect: Effect[Mix], strip: Strip,
              position: float = 0.0):
        owner.run_effect(effect)
        return super().paint(owner, effect, strip, position)

    def on_new_arrival(self, owner: LineHistory, effect: Effect[Mix], pages: deque[TranscriptPageView]):
        owner.arrivals_began()


class EffectFinished(EffectPhase):
    def keeps_arrivals[Item](self, arrivals: Iterable[Item]) -> Iterable[Item]:
        return ()

    def on_new_arrival(self, owner: LineHistory, effect: Effect[Mix], pages: deque[TranscriptPageView]):
        for page in pages:
            page.arrivals.clear()
        owner.stop_effect(effect)
        owner.arrivals_began()


EFFECT_UNSTARTED, EFFECT_FINISHED = EffectUnstarted(), EffectFinished()


class RowRun:
    """Something drawn as a run of rows, which a cascade plays across.

    One declaration of where a row stands in its run, and one of how many rows it has:
    the height the last layout gave it. Counting from the content instead (summing its
    prepared rows) measures during paint and scroll, which stalls layout: a live block of
    128 paragraphs never settled its height
    (tests/textual/test_transcript_presentation_fencing.py).
    """

    drawn_rows: int = 0
    """How many rows the last layout gave this run."""

    @on(events.Resize)
    def on_resize(self, event: events.Resize) -> None:
        self.drawn_rows = event.size.height

    def cascade_rows(self) -> int:
        """How many rows the run draws."""
        return self.drawn_rows

    def row_position(self, y: int) -> float:
        """How far row `y` is through the run: 0 the first row, 1 the last."""
        rows = self.cascade_rows()
        return y / (rows - 1) if rows > 1 else 0.0


@dataclass(frozen=True)
class ArrivalRun(RowRun):
    """A run whose rows need not be contiguous: the rows a page draws for its arriving
    fragments, in drawing order.

    Rows between two arriving fragments belong to older messages and are not in the run.
    Reading the run as the whole span from the first arriving row to the last counted every
    row in between as arriving, so a following tail stopped that far above the newest
    message (2026-11-07: "my viewpoert randomly scrolled way up outof nowhere in this clib
    rbdige inbox").
    """

    spans: tuple[range, ...] = ()

    def cascade_rows(self) -> int:
        return sum(len(span) for span in self.spans)

    def row_position(self, y: int) -> float:
        rows = self.cascade_rows()
        if rows < 2:
            return 0.0
        passed = 0
        for span in self.spans:
            if y in span:
                return (passed + y - span.start) / (rows - 1)
            passed += len(span)
        return 0.0


class FollowsUnrisenRows:
    """A scrolling view that keeps a following reader above the rows still rising.

    Implemented by `HistoryWindow`: it owns both the tail and the reader, and the cascades
    inside it tell it, every frame, that their front has moved (`CascadingRows.frame_moved`).
    """

    def rows_revealed(self) -> None:
        """Another frame of a cascade below: re-place a reader who follows the tail."""


NOT_FOLLOWED = FollowsUnrisenRows()
"""Nobody follows this holder's rows, so a frame of its reveal moves no reader: a widget
mounted outside a window, or one whose window has not taken it yet."""


class UnrisenRows:
    """Something that can hold arriving rows below a following reader until they rise.

    A window following its tail stops above them (`HistoryWindow.tail_scroll_y`), so the
    rows reveal under a tail that waits for them instead of behind one already at the end.
    Holding nothing back is the default: most of what a window mounts never cascades.
    """

    following: FollowsUnrisenRows = NOT_FOLLOWED
    """Who to tell when this holder's reveal moves. The window hands itself over as the
    holder registers (it already keeps every one of them), rather than the holder walking
    its ancestors asking each one whether it follows rows: that probe is what
    tests/guards/test_prompt_frame.py bans at this boundary, and it is right to."""

    def followed_by(self, window: FollowsUnrisenRows) -> None:
        self.following = window

    def unrevealed_rows(self) -> int:
        return 0


class AnimationEffects[FrameT: Frame](TonePaint):
    """A native widget whose effect uses the app clock and published visibility."""

    text_fades: ClassVar[tuple[TextFade, ...]] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.effects: dict[Effect, EffectRunning] = {}
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
                self.effects[effect] = EffectRunning(self.app.colours.clock.start(effect, self))
                if effect.finite:
                    self.wanted.discard(effect)

    def stop_effect(self, *effects: Effect) -> None:
        if effects:
            self.wanted.difference_update(effects)
        else:
            self.wanted.clear()
        for effect in effects or tuple(self.effects):
            self.effects.pop(effect, EFFECT_UNSTARTED).stop()

    def effect_frame[Shown: Frame](self, effect: Effect[Shown], position: float = 0.0) -> Shown:
        return self.effects.get(effect, EFFECT_UNSTARTED).shown(
            effect, self.animation_visible, position)

    def effect_phase(self, effect: Effect[FrameT]) -> EffectPhase:
        return self.effects.get(effect, EFFECT_UNSTARTED).now()

    async def on_unmount(self) -> None:
        self.stop_effect()

    def on_hide(self) -> None:
        for effect in tuple(self.effects):
            self.effects.pop(effect).stop()
        self.repaint()

    def on_show(self) -> None:
        self.start_wanted()
        self.repaint()

    def paint_effects(self, strip: Strip, *frames: Mix, position: float = 0.0) -> Strip:
        # Background-origin text rises from the widget's tone; accent flashes
        # keep their declared origin. Both finish at each run's own ink.
        # `position` is the row being drawn: an effect that plays row after row uses it,
        # and one that treats its rows alike ignores it (Effect.at).
        for frame in (
            *frames,
            *(
                (
                    replace(self.effect_frame(effect, position), start=self.text_background)
                    if effect.start is BackgroundColour
                    else self.effect_frame(effect, position)
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
        """What the clock calls on each frame of this widget's effects: what the frame moved,
        then the redraw that shows it. Two questions, so two methods: every widget here has a
        redraw policy and overrode this one for it, which left a frame with nowhere to say
        that a reveal had advanced."""
        self.frame_moved()
        self.redraw()

    def frame_moved(self) -> None:
        """What this frame changed beyond the widget's own pixels; nothing, for most."""

    def redraw(self) -> None:
        """A frame paints over the lines (paint_effects in render_line); the content they
        show is unchanged, so it is not rendered again."""
        self.repaint_lines()


class EffectInContent:
    """A widget whose content itself reads the effect frame (in render or its strips), so each
    frame renders the content again instead of repainting the same lines."""

    def redraw(self) -> None:
        self.refresh()


class CascadingRows(UnrisenRows, AnimationEffects[Mix]):
    """A widget whose arriving rows rise one after another, in runs it declares.

    Each run holds its own rows back while its front climbs, which is why the pager
    reports per page and a live entry per row widget: the cascade restarts with each
    run, so one run's unrisen rows say nothing about another's.
    """

    @cached_property
    def row_runs(self) -> WeakSet[RowRun]:
        """Every prepared-row widget drawing inside this one; each adds itself when it mounts,
        so an entry needs no DOM query and no import of the widget that draws its rows."""
        return WeakSet()

    def drawing_rows(self, run: RowRun) -> None:
        self.row_runs.add(run)

    def cascade_runs(self) -> Iterable[int]:
        """Each run of arriving rows this widget draws, by row count."""
        return (run.cascade_rows() for run in self.row_runs)

    def unrevealed_rows(self) -> int:
        phase = self.effect_phase(ARRIVAL)
        return sum(phase.unrevealed(ARRIVAL, rows) for rows in self.cascade_runs())

    def frame_moved(self) -> None:
        """The cascade's front has moved down since the last frame, so whoever follows these
        rows re-places its reader. Reporting rows held back is not enough on its own: nothing
        re-reads the tail between frames, so a window already at the end stayed there while
        the rows rose under it.

        Only while rows are actually held back, because re-placing a reader is a scroll and a
        scroll is layout: a block whose rows were still being measured moved the reader on
        every frame, and the churn kept a 128-paragraph answer from ever settling its height
        (tests/textual/test_transcript_presentation_fencing.py).
        """
        if self.unrevealed_rows():
            self.following.rows_revealed()


class Animated[FrameT: Frame](AnimationEffects[FrameT], Widget, RowRun):
    """A widget whose own rendered rows receive its declared text fades.

    `RowRun` sits after `Widget` because the row widgets it shares that contract with
    reach it behind their own message pump (`LinkedRows`): one order for both, or a
    class that is both has no linearization.
    """

    # The row count comes from the layout that set it (RowRun.on_resize), never from a
    # measurement taken while painting: reading self.size in render_line stalls a scrolling
    # container's paging (test_channel_scrolling's held paging stopped moving).

    def render_line(self, y: int, paint: PaintState) -> Strip:
        return self.paint_effects(super().render_line(y, paint), position=self.row_position(y))
