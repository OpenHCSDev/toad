"""One pointer gesture on a draggable control, for every frontend.

A press that moves past the control's ``drag_threshold`` becomes a drag; a press released
before that is a click. Textual's `CapturedDrag` and Qt's `QtGripPointer` both feed their own
pointer events into these states, so a click and a drag mean the same on either.
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


class Gesture:
    """Where one pointer gesture on a control stands: nothing, a press, or a drag."""

    # Whether a newer pointer move may replace a pending one: only while the gesture holds it.
    holds_pointer: ClassVar[bool] = True

    def moved(self, control: GestureControl, position: Offset) -> Gesture:
        return self

    def released(self, control: GestureControl, position: Offset) -> Gesture:
        return NO_GESTURE


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


class DraggingGesture(Gesture):
    def moved(self, control: GestureControl, position: Offset) -> Gesture:
        control.drag_to(position)
        return self

    def released(self, control: GestureControl, position: Offset) -> Gesture:
        control.drag_to(position)
        control.dragged()
        return NO_GESTURE


NO_GESTURE, DRAGGING = NoGesture(), DraggingGesture()
