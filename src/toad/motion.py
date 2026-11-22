"""Motion every frontend shares, beside ui_theme's own effects.

ui_theme declares how a sidebar enters and leaves (``SIDEBAR_ENTER`` / ``SIDEBAR_EXIT``) and how
a chosen tab's underline wipes in (``TAB_WIPE``). A tab opening or closing grows from nothing
and shrinks away on the same eased transition, quicker than a sidebar because a tab is small.
Both run on the frontend's one `AnimationClock`, so turning animation off (Textual's
``TEXTUAL_ANIMATIONS=none``) stops them everywhere at once.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from textual import constants
from ui_theme.clock import AnimationClock
from ui_theme.effects import Amount, Effect, Glide, Transition

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


class AmbientBudget:
    """How much of the thread that serves the reader its ambient motion may take.

    A busy sweep and the waving names move for as long as any agent works. A frontend whose
    frames cost that thread something tells this what each frame it showed cost; the clock
    then affords ambient motion a frame only as often as keeps it within `SHARE` of the
    thread (`AnimationClock.ambient_interval`). A Pixel 8a's widget window takes about 27 ms
    to paint and show a frame, so its sweep and waves step about 5 times a second and leave
    the thread to scrolling and keys; a desktop's 1 ms frame leaves them at their own 20.
    Nothing is tuned per device, and a frame made cheaper speeds them up again by itself."""

    SHARE = 0.15
    NEWEST = 0.2
    """The newest frame's weight in the running cost: a few frames move it, one does not."""
    STEP = 0.02
    """The interval moves in steps this long, so the clock's timer is not set again for each
    frame's slightly different cost."""

    def __init__(self, clock: AnimationClock) -> None:
        self.clock = clock
        self.cost = 0.0

    def frame_shown(self, seconds: float) -> None:
        """A frame was painted and shown, holding the thread for `seconds`."""
        self.cost += self.NEWEST * (seconds - self.cost)
        afforded = round(self.cost / self.SHARE / self.STEP) * self.STEP
        if afforded != self.clock.ambient_interval:
            self.clock.ambient_interval = afforded


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
