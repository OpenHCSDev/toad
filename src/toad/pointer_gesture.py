"""One pointer gesture on a control, for every frontend.

A press that moves past the control's ``drag_threshold`` becomes a drag; a press released
before that is a click; a press its control reports held (still, for the platform's
press-and-hold time) becomes a hold, which the control answers or doesn't. Textual's
`CapturedDrag`, Qt's `QtGripPointer` and Qt's application-wide `FingerPress` feed their own
pointer events into these states, so a click, a drag and a hold mean the same on each.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from textual.geometry import Offset


class GestureControl:
    """A control a gesture drives: it maps positions to its own effect."""

    # How far a press may wander, in the units positions arrive in, and still be a click.
    drag_threshold: ClassVar[int] = 0

    @abstractmethod
    def drag_to(self, position: Offset) -> None:
        """The pointer, held, is at ``position``."""

    def clicked(self) -> None:
        """A press released without a drag: by default it does nothing."""

    def dragged(self) -> None:
        """A drag let go, after its last ``drag_to``: by default nothing more happens."""

    def held(self) -> bool:
        """A press held still: the control answers with what a hold means to it (a menu) and
        says whether it did. By default a hold means nothing and the press goes on."""
        return False


class Gesture:
    """Where one pointer gesture on a control stands: nothing, a press, a drag or a hold."""

    # Whether a newer pointer move may replace a pending one: only while the gesture holds it.
    holds_pointer: ClassVar[bool] = True
    # Whether the gesture's moves and release are its control's alone, kept from the widget
    # under the pointer: only a hold the control answered.
    takes_pointer: ClassVar[bool] = False

    def moved(self, control: GestureControl, position: Offset) -> Gesture:
        return self

    def released(self, control: GestureControl, position: Offset) -> Gesture:
        return NO_GESTURE

    def held(self, control: GestureControl) -> Gesture:
        """The press has been held still: only a press not yet a drag becomes a hold."""
        return self


class NoGesture(Gesture):
    holds_pointer = False


@dataclass(frozen=True)
class PressedGesture(Gesture):
    start: Offset

    def moved(self, control: GestureControl, position: Offset) -> Gesture:
        travel = position - self.start
        if abs(travel.x) + abs(travel.y) <= control.drag_threshold:
            return self
        control.drag_to(position)
        return DRAGGING

    def released(self, control: GestureControl, position: Offset) -> Gesture:
        control.clicked()
        return NO_GESTURE

    def held(self, control: GestureControl) -> Gesture:
        return HELD if control.held() else UNANSWERED_HOLD


class HeldGesture(Gesture):
    """A hold its control answered: the rest of the press is the answer's, so its moves and
    release reach nothing else, and letting go is not a click."""

    takes_pointer = True


class UnansweredHold(Gesture):
    """A hold its control had no answer for: the press goes on as the widget under it takes
    it, and letting go is not a click."""


class DraggingGesture(Gesture):
    def moved(self, control: GestureControl, position: Offset) -> Gesture:
        control.drag_to(position)
        return self

    def released(self, control: GestureControl, position: Offset) -> Gesture:
        control.drag_to(position)
        control.dragged()
        return NO_GESTURE


NO_GESTURE, DRAGGING = NoGesture(), DraggingGesture()
HELD, UNANSWERED_HOLD = HeldGesture(), UnansweredHold()
