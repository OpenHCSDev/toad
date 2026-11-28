"""The application's grant of finger scrolling holds a scroll area once via `QProxyStyle.polish`
with zero application-wide event filter overhead (`toad.qt.finger_scrolling`)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QScrollArea, QScroller, QWidget

from toad.qt.finger_scrolling import FingerScrolling, MouseAndWheel, TouchAsMouse


class Grabbed:
    def __init__(self) -> None:
        self.viewports = []

    def grab(self, viewport) -> None:
        self.viewports.append(viewport)


def test_a_scroll_area_is_held_at_its_polish_via_proxy_style(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    gesture = Grabbed()
    granted = FingerScrolling(gesture, application)
    plain, scrolling = QWidget(), QListWidget()
    try:
        granted.polish(plain)
        assert gesture.viewports == []
        granted.polish(scrolling)
        assert gesture.viewports == [scrolling.viewport()]
    finally:
        plain.deleteLater()
        scrolling.deleteLater()
        granted.deleteLater()


def test_touch_attaches_proxy_style_without_app_event_filter():
    styled = []
    base_styles = []
    filtered = []

    class FakeStyle:
        pass

    class FakeGranted:
        def setBaseStyle(self, base):
            base_styles.append(base)

    class FakeApplication:
        def __init__(self):
            self._style = FakeStyle()

        def allWidgets(self):
            return []

        def style(self):
            return self._style

        def setStyle(self, style):
            styled.append(style)

        def installEventFilter(self, flt):
            filtered.append(flt)

    app = FakeApplication()
    marker = FakeGranted()
    MouseAndWheel().attach(app, marker)
    assert styled == []
    assert filtered == []
    TouchAsMouse().attach(app, marker)
    assert base_styles == [app._style]
    assert styled == [marker]
    assert filtered == []


def test_touch_grab_is_idempotent_across_repolish(monkeypatch):
    """Repeated `polish()` calls must keep the same QScroller gesture ID instead of
    unregistering and deleting the active `QFlickGestureRecognizer`."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    gesture = TouchAsMouse()
    granted = FingerScrolling(gesture, application)
    area = QScrollArea()
    try:
        vp = area.viewport()
        granted.polish(area)
        first = QScroller.grabbedGesture(vp)
        assert first.value > Qt.GestureType.CustomGesture.value
        for _ in range(5):
            granted.polish(area)
            gesture.grab(vp)
            assert QScroller.grabbedGesture(vp) == first
    finally:
        QScroller.ungrabGesture(area.viewport())
        area.deleteLater()
        granted.deleteLater()
