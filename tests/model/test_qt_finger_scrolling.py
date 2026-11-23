"""The application's grant of finger scrolling holds a scroll area as Qt polishes it, and
asks what is watched before it reads anything of an event (`toad.qt.finger_scrolling`)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

from toad.qt.finger_scrolling import FingerScrolling, MouseAndWheel, TouchAsMouse


class Grabbed:
    def __init__(self) -> None:
        self.viewports = []

    def grab(self, viewport) -> None:
        self.viewports.append(viewport)


class Untouchable:
    def __getattr__(self, name):
        raise AssertionError(f"read {name} of an event sent to something that never scrolls")


def test_a_scroll_area_is_held_at_its_polish_and_nothing_else_is_read(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    gesture = Grabbed()
    granted = FingerScrolling(gesture, application)
    plain, scrolling = QWidget(), QListWidget()
    try:
        # Every event of every object passes the filter: one for a plain widget or a bare
        # object is answered by what it was sent to, with nothing of the event read.
        assert granted.eventFilter(plain, Untouchable()) is False
        assert granted.eventFilter(QObject(), Untouchable()) is False
        assert granted.eventFilter(scrolling, QEvent(QEvent.Type.Paint)) is False
        assert gesture.viewports == []

        assert granted.eventFilter(scrolling, QEvent(QEvent.Type.Polish)) is False
        assert gesture.viewports == [scrolling.viewport()]
    finally:
        plain.deleteLater()
        scrolling.deleteLater()
        granted.deleteLater()


def test_desktop_mouse_gesture_skips_app_wide_event_filter():
    assert MouseAndWheel.installs_filter is False
    assert TouchAsMouse.installs_filter is True
