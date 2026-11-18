"""What a press is: a tap, a held finger, or the start of a drag, decided once for the app.

A press reaches Qt as the window's mouse event (Android synthesizes it from the finger), then
widget by widget down to the one under it, each of which might guess on its own whether it
was a tap or a hold. Toad had two such guesses (the sidebar tree's and the history's
TapAndHold gestures, the sidebar's with a filter that ate the release after it), and widgets
that offer a menu on right-click had no hold at all. Here the application classifies each
press once, at its window, through the shared `toad.pointer_gesture` states with the
platform's drag distance and press-and-hold interval:

- a finger held still for the press-and-hold interval is a right-click: the widget under it
  gets the `QContextMenuEvent` a right button would send, so every context menu (a
  `customContextMenuRequested` connection or a `contextMenuEvent` override) answers a held
  finger with no code of its own. A hold its widgets offer no menu for stays a press;
- a press that moves past the drag distance first is a drag (finger scrolling, a grip, a
  reordered tab), and nothing else happens to it;
- a press released before either is a tap. A tap's consumers (`tapped`) hear it before the
  widget does and may `claim` it, which ends the press without the widget's own click.

A mouse's press is classified as a tap or a drag the same way. Holding a mouse button is not
a right-click, because a mouse has one.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent, QInputDevice, QInputMethodQueryEvent, QMouseEvent, QWindow
from PySide6.QtWidgets import QApplication, QWidget
from textual.geometry import Offset

from toad.pointer_gesture import DRAGGING, NO_GESTURE, Gesture, GestureControl, PressedGesture

# Qt has no cancelled mouse press. A release this far outside every widget ends the press in
# the widget that took it (the window routes a release to its press's receiver), and no Qt
# control counts a release outside itself as a click.
_NOWHERE = QPointF(-1e5, -1e5)


class Press:
    """One press, from the window's first event to its release."""

    __slots__ = ("target", "origin", "finger", "claimed")

    def __init__(self, target: QWidget | None, origin: QPointF, finger: bool) -> None:
        self.target = target
        """The deepest widget under the press when it began."""
        self.origin = origin
        """Where it began, in global coordinates."""
        self.finger = finger
        """A finger on a touch screen rather than a mouse."""
        self.claimed = False

    def within(self, widget: QWidget) -> bool:
        """The press began on ``widget`` or on one of its children."""
        return self.target is not None and (widget is self.target or widget.isAncestorOf(self.target))

    def at(self, widget: QWidget) -> QPoint:
        """Where the press began, in ``widget``'s coordinates."""
        return widget.mapFromGlobal(self.origin.toPoint())

    def claim(self) -> None:
        """A tap's consumer took it: the press ends without the widget's own click."""
        self.claimed = True


class FingerPress(QObject, GestureControl):
    """The application's one classifier of presses (see the module): a `GestureControl` fed
    every press its windows receive."""

    tapped = Signal(object)
    """A `Press` released before it moved past the drag distance or was held. Delivered
    before the release reaches the widget, so a consumer may `claim` it."""
    long_pressed = Signal(object)
    """A finger's `Press` held still, which the widget under it answered with a menu."""
    drag_started = Signal(object)
    """A `Press` that moved past the drag distance."""

    def __init__(self, application: QApplication) -> None:
        QObject.__init__(self, application)
        hints = application.styleHints()
        self.drag_threshold = hints.startDragDistance()
        self.hold = QTimer(self, singleShot=True, interval=hints.mousePressAndHoldInterval())
        self.hold.timeout.connect(self._held_still)
        self.gesture: Gesture = NO_GESTURE
        self.press: Press | None = None
        self.window: QWindow | None = None

    @classmethod
    def install(cls, application: QApplication) -> FingerPress:
        """The application's classifier; installing again (a consumer asking for it) returns
        the one already held."""
        held = application.findChild(cls)
        if held is not None:
            return held
        classifier = cls(application)
        application.installEventFilter(classifier)
        return classifier

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # A press is seen once, at its window, before Qt routes it down to a widget (and
        # before QScroller holds it back); a widget's copy of the same press is not counted.
        if not isinstance(watched, QWindow) or not isinstance(event, QMouseEvent):
            return False
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if self.press is None:
                self._began(watched, event)
            return False
        if self.press is None or watched is not self.window:
            return False
        if kind == QEvent.Type.MouseMove:
            pressed = self.gesture
            self.gesture = pressed.moved(self, _offset(event))
            if self.gesture is DRAGGING and pressed is not DRAGGING:
                self.hold.stop()
                self.drag_started.emit(self.press)
            return self.gesture.takes_pointer
        if kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            gesture, press = self.gesture, self.press
            self.gesture = gesture.released(self, _offset(event))
            self._ended()
            if gesture.takes_pointer or press.claimed:
                self._cancel(event)
                return True
        return False

    def clicked(self) -> None:
        self.tapped.emit(self.press)

    def drag_to(self, position: Offset) -> None:
        """A drag's moves are the widget's own (a scroll, a grip, a reorder)."""

    def held(self) -> bool:
        """The widget under a finger held still gets a right-click's context-menu request;
        the hold is answered when one of its widgets offers a menu (accepts the event)."""
        press = self.press
        if press.target is None or _platform_edits_text(press):
            # The focused text field's own long-press is the platform's (selection handles,
            # the system's copy and paste); a held finger there is not a right-click.
            return False
        menu = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, press.at(press.target), press.origin.toPoint())
        QApplication.sendEvent(press.target, menu)
        if menu.isAccepted():
            self.long_pressed.emit(press)
            return True
        return False

    def _began(self, window: QWindow, event: QMouseEvent) -> None:
        origin = event.globalPosition()
        finger = event.device().type() == QInputDevice.DeviceType.TouchScreen
        self.press = Press(_widget_at(window, event.scenePosition()), origin, finger)
        self.window, self.gesture = window, PressedGesture(_offset(event))
        if finger:
            self.hold.start()

    def _held_still(self) -> None:
        if self.press is not None:
            self.gesture = self.gesture.held(self)

    def _ended(self) -> None:
        self.hold.stop()
        self.press = None

    def _cancel(self, event: QMouseEvent) -> None:
        """End the press in the widget that took it, without its click."""
        window, self.window = self.window, None
        cancel = QMouseEvent(QEvent.Type.MouseButtonRelease, _NOWHERE, _NOWHERE, window.mapToGlobal(_NOWHERE),
                             Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, event.modifiers(), event.device())
        QApplication.sendEvent(window, cancel)


def _offset(event: QMouseEvent) -> Offset:
    position = event.globalPosition()
    return Offset(round(position.x()), round(position.y()))


def _widget_at(window: QWindow, point: QPointF) -> QWidget | None:
    for widget in QApplication.topLevelWidgets():
        if widget.windowHandle() is window:
            return widget.childAt(point.toPoint()) or widget
    return None


def _platform_edits_text(press: Press) -> bool:
    """The press is on the focused widget, and that widget takes text input: Qt-for-Android
    gives a hold there to the platform's text selection, as it does for exactly this widget."""
    focus = QApplication.focusWidget()
    if focus is None or not press.within(focus):
        return False
    query = QInputMethodQueryEvent(Qt.InputMethodQuery.ImEnabled)
    QApplication.sendEvent(focus, query)
    return bool(query.value(Qt.InputMethodQuery.ImEnabled))
