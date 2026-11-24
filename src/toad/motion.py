"""Motion every frontend shares, beside ui_theme's own effects.

ui_theme declares how a sidebar enters and leaves (``SIDEBAR_ENTER`` / ``SIDEBAR_EXIT``) and how
a chosen tab's underline wipes in (``TAB_WIPE``). A tab opening or closing grows from nothing
and shrinks away on the same eased transition, quicker than a sidebar because a tab is small.
Both run on the frontend's one `AnimationClock`, so turning animation off (Textual's
``TEXTUAL_ANIMATIONS=none``) stops them everywhere at once.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from textual import constants
from ui_theme.clock import AnimationClock
from ui_theme.effects import Amount, Effect, Fade, Glide, Mix, NEW_TEXT, TextFade, Transition
from ui_theme.scheme import ThemeColour

_TAB_DURATION = 0.15
_TAB_FPS = 60
TAB_OPEN = Transition(Amount, 0.0, 1.0, _TAB_DURATION, _TAB_FPS)
TAB_CLOSE = Transition(Amount, 1.0, 0.0, _TAB_DURATION, _TAB_FPS)
# A reader following the end glides down to rows that arrived, over the time the first of them
# takes to fade in (``ARRIVAL``'s `NEW_TEXT`), instead of jumping their whole height at once. It
# is motion, so it moves on every frame the screen shows (120 on a Pixel 8a), not a fixed 60.
FOLLOW_ARRIVAL = Glide(Amount, 0.0, 1.0, 0.25)
# A row under the composer (the queue summary, the delivery controls) opens or closes its height
# instead of appearing in one frame and pushing the history up.
ROW_REVEAL = Transition(Amount, 0.0, 1.0, _TAB_DURATION, _TAB_FPS)
# A scrollbar drawn over the text while it moves fades away once it has been still a moment,
# rather than vanishing in one frame.
SCROLLBAR_FADE = Transition(Amount, 1.0, 0.0, 0.3, _TAB_FPS)

# A tapped message whose head is above the viewport glides its head to the top, rather than
# the view jumping there in one frame.
HEAD_REVEAL = Glide(Amount, 0.0, 1.0, 0.18)


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


def animations_enabled() -> bool:
    """Whether this process animates: Textual's own animation level, which the TUI's clock
    already follows, so one environment setting turns motion off in both frontends."""
    return constants.TEXTUAL_ANIMATIONS != "none"


class TransitionTarget(ABC):
    """One finite transition on a frontend's clock: each frame applies the effect's amount, and
    the last one lands it where it was going. A pane sliding, a tab growing in and a closed tab
    shrinking away are all this; each frontend only says what an amount moves.

    It advances by what it showed, not by the wall clock: a tick counts at most two of the
    effect's frames (its cadence on this clock's medium), so a loop held up by other work (opening a session, say) delays the motion
    rather than skipping it, and every transition is seen from start to end."""

    def start_transition(self, clock: AnimationClock, effect: Effect[Amount]) -> None:
        self.clock, self.effect = clock, effect
        self.shown_for = 0.0
        self.shown_at = clock.now()
        self.animation = clock.start(effect, self)

    @property
    @abstractmethod
    def animation_visible(self) -> bool:
        """Whether the moving thing is on screen, so the clock ticks at the effect's cadence."""

    @abstractmethod
    def apply_amount(self, amount: float) -> None:
        """Show the transition ``amount`` of the way between its two ends."""

    @abstractmethod
    def land(self) -> None:
        """The transition ended or was cut short: show where it was going."""

    def finish(self) -> None:
        self.animation.stop()
        self.land()

    def repaint(self) -> None:
        now = self.clock.time
        self.shown_for += min(now - self.shown_at, 2 * self.effect.cadence.interval(self.clock.frame_interval))
        self.shown_at = now
        if self.shown_for >= self.effect.duration:
            self.finish()
            return
        if self.animation.finished:
            # The wall clock ran out while the loop was busy; keep ticking until it is shown.
            self.animation = self.clock.start(self.effect, self)
        self.apply_amount(self.effect.frame(self.shown_for).value)
