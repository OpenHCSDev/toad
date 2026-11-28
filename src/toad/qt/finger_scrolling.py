"""Every Qt scroll area scrolls by finger: one application-level owner of QScroller's grab.

Qt widgets on Android scroll only by their scroll bar unless a QScroller holds the
viewport. Toad held it per class (pyqt-reactive's `TouchScrolled` on the history window
and the sidebar tree), so the settings pages, the view-settings picker, the keymap table,
the transfer and goal dialogs, the welcome lists, dropdown popups and the composer scrolled
only by their bar. Here the application grants the grab once, to every scroll area as Qt
polishes it, so a scroll area added later scrolls by finger without opting in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QProxyStyle, QScroller, QWidget


class FingerScrollGesture(ABC):
    """What a drag on a scroll area's viewport means on this platform."""

    @abstractmethod
    def grab(self, viewport: QWidget) -> None:
        """Make a drag on ``viewport`` scroll it, if this platform's drags should."""

    def attach(self, application: QApplication, granted: FingerScrolling) -> None:
        """Install the proxy style so Qt's C++ polish hook grabs every new scroll area once
        at creation, with zero per-event Python filter overhead."""
        for widget in application.allWidgets():
            granted.held(widget)
        granted.setBaseStyle(application.style())
        application.setStyle(granted)

    @staticmethod
    def of_platform() -> FingerScrollGesture:
        """Android delivers a finger as a mouse Qt synthesizes from the touch, so a drag is a
        finger and scrolls kinetically; a desktop's drag is a mouse selecting text or
        dragging rows, and its wheel and scroll bars scroll."""
        return TouchAsMouse() if QGuiApplication.platformName() == "android" else MouseAndWheel()


class TouchAsMouse(FingerScrollGesture):
    """A drag scrolls with momentum. QScroller holds a press back until it is clearly not a
    drag, then delivers it, so a tap still presses the row or button under the finger."""

    def grab(self, viewport: QWidget) -> None:
        """Grab once per viewport: calling `QScroller.grabGesture` again unregisters and
        deletes the live `QFlickGestureRecognizer`, leaving `QGestureManager::getState`
        with a dangling recognizer pointer when a widget repolishes during gesture delivery."""
        if QScroller.grabbedGesture(viewport).value <= Qt.GestureType.CustomGesture.value:
            QScroller.grabGesture(viewport, QScroller.ScrollerGestureType.LeftMouseButtonGesture)


class MouseAndWheel(FingerScrollGesture):
    """A drag is the mouse's own: it selects text in a field or moves a row. Holding it for
    scrolling would stop a form's text from being selected by dragging across it."""

    def grab(self, viewport: QWidget) -> None:
        pass

    def attach(self, application: QApplication, granted: FingerScrolling) -> None:
        pass


class FingerScrolling(QProxyStyle):
    """The application's one grant of finger scrolling: every `QAbstractScrollArea` (item
    views, text edits, scroll areas, a dropdown's popup list) is held once as Qt's style
    polishes it — zero application-wide `eventFilter` calls on timers, paints or scrolls."""

    def __init__(self, gesture: FingerScrollGesture, application: QApplication) -> None:
        super().__init__()
        self.setParent(application)
        self.gesture = gesture

    @classmethod
    def install(cls, application: QApplication, gesture: FingerScrollGesture) -> FingerScrolling:
        """The application's grant; the first install's gesture holds for the process, so a
        drive can choose the phone's gesture before the client opens."""
        if isinstance(application.style(), cls):
            return application.style()
        held = application.findChild(cls)
        if held is not None:
            return held
        granted = cls(gesture, application)
        gesture.attach(application, granted)
        return granted

    def held(self, widget: QObject) -> None:
        if isinstance(widget, QAbstractScrollArea):
            self.gesture.grab(widget.viewport())

    def polish(self, arg) -> None:  # type: ignore[override]
        if isinstance(arg, QAbstractScrollArea):
            self.gesture.grab(arg.viewport())
        super().polish(arg)
