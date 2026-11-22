"""How the APK's start asks Qt to show a widget window's frames."""

from __future__ import annotations

from PySide6.QtGui import QSurfaceFormat

from toad.qt import android


def test_android_windows_are_made_to_show_frames_without_waiting_for_a_refresh() -> None:
    """A window made after the start asks its swap chain for no wait (Qt reads the default
    format's swap interval when it makes one): the GUI thread is not held for each frame."""
    before = QSurfaceFormat.defaultFormat()
    try:
        assert before.swapInterval() != 0  # Qt's own default waits
        android.show_frames_without_waiting()
        assert QSurfaceFormat.defaultFormat().swapInterval() == 0
    finally:
        QSurfaceFormat.setDefaultFormat(before)
