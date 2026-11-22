"""The APK's start: Toad's Qt client on this phone, on the first bus it holds.

The APK's `main.py` (tools/android/main.py) enters the APK's environment
(toad.qt.android_app) and then runs `main` here.

The APK's activity (tools/android/keepalive) holds the process in the foreground with an
ongoing notification, so switching away leaves Toad running; once suspended, the app
gives the memory it can rebuild back to Android (SuspendedMemory).

A failure before the window opens POSTs its traceback to the dev crash sink on the tailnet
(toad.client.host.post_crash_to_sink) and saves it under the state folder, since a phone
without adb has nowhere else to show it, and a top-level QMessageBox on Qt-for-Android
needs its own EGL surface and deadlocks with the compositor on this platform (SIGABRT,
QAndroidPlatformOpenGLWindow::eglSurface deadlock protector). SessionRecord notes each
state Android moves the app through, so the next start's log says how the last ended.
"""

import ctypes
import gc
import os
import sys
import threading
import time
import traceback
from collections.abc import Iterator

from PySide6 import QtWidgets
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from toad import paths
from toad.fatal_trace import FatalTrace
from toad.qt.android_app import KEPT
from toad.qt.frame_probe import FrameProbe
from toad.qt.splash import QtSplash
from toad.qt.theme import current_scheme


class SessionRecord:
    """The states Android moved this run of the app through, one line each, kept so the next
    start can say how this one ended.

    Closing the window ends it with `closed`, and a failure Toad shows with `failed`. Android
    ends a process without telling it: when it kills a backgrounded app for memory, and when
    the activity is destroyed (Qt's QtActivityBase.onDestroy and p4a's PythonActivity.onDestroy
    both exit the process, and an activity created again in a live process restarts it). Each
    of those leaves the last recorded state as the line the next start reads. Lines are written through as they happen,
    so a killed process still leaves them; the file holds one run, replaced at each start.
    """

    PATH = KEPT / "state" / "android-lifecycle.log"

    def __init__(self, now: float) -> None:
        self.previous = self.PATH.read_text().splitlines() if self.PATH.is_file() else []
        self.PATH.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.PATH.open("w", buffering=1)
        self.write(now, "started")

    def write(self, when: float, event: str) -> None:
        self.log.write(f"{when:.0f} {event}\n")

    def changed(self, state: Qt.ApplicationState) -> None:
        self.write(time.time(), state.name)

    def ended(self, how: str) -> None:
        self.write(time.time(), how)


class SuspendedMemory:
    """What the suspended app gives back to Android. On the same suspend, pyqt-reactive's row
    views let their laid-out documents go (RowDocumentDelegate.release_documents); the
    allocator would keep that freed memory for reuse, so once every owner has dropped what
    it can rebuild, bionic's M_PURGE returns it to the system."""

    M_PURGE = -101
    """bionic's malloc.h, Android 9 and later."""

    def __init__(self) -> None:
        self.libc = ctypes.CDLL("libc.so")

    def changed(self, state: Qt.ApplicationState) -> None:
        if state is Qt.ApplicationState.ApplicationSuspended:
            # After every other owner's answer to this suspend: the views connect later.
            QTimer.singleShot(0, self.release)

    def release(self) -> None:
        gc.collect()
        self.libc.mallopt(self.M_PURGE, 0)


def _install_excepthook() -> None:
    """Belt and suspenders beside the except BaseException clause below: a Qt slot that
    raises on Android bypasses the asyncio loop's except, and sys.__excepthook__ prints to
    stderr that nothing reads. This hook also saves and posts every uncaught exception,
    so the traceback leaves the device even when the crash is a direct Qt kill."""
    previous = sys.excepthook

    def hook(kind: type[BaseException], value: BaseException, tb) -> None:
        try:
            saved_path = paths.save_error(value, "android_uncaught")
            from toad.client.host import post_crash_to_sink

            threading.Thread(
                target=post_crash_to_sink,
                args=(saved_path, "android_uncaught", f"Toad uncaught: {kind.__name__}"),
                daemon=True,
            ).start()
        except BaseException:  # the hook must not raise, or Python's default handler aborts
            pass
        previous(kind, value, tb)

    sys.excepthook = hook


def load_client():
    """Load the client (Core's wire records, the transport, every view): most of a start.
    The first frame is up by now. The APK's closure and its checks load it through this
    same call, so what they bundle and check is what runs. Answers the function that
    serves the held bus."""
    from toad.qt.android_bus import serve_held

    return serve_held


def whole_pixel_ratio() -> None:
    """Draw at a whole number of device pixels to each of Qt's, so a scroll moves pixels.

    Qt scrolls a viewport by moving the pixels it already drew and painting the strip that
    came into view, but only when the distance is a whole number of device pixels
    (`QBackingStore::scroll`); otherwise it paints every scrolled row again. A Pixel 8a's
    ratio is 2.625 (21/8), so seven scroll steps of eight repainted the whole message list:
    measured on that ratio (2026-11-21, a finger drag back through #comms), 7720 of 8724
    scrolled paints covered over 90% of the viewport and 992 under 20%, one in eight.

    Rounded, the ratio is 3. Qt puts the remainder into the screen's logical DPI (72 becomes
    63), so text sized in points keeps its physical size and as many characters fit a line
    (`fonts_in_points` puts Android's fonts in points); lengths written in pixels (margins,
    rules) grow by a seventh. It is read when the application is made, so this runs first.
    The frame probe's `display` line records the ratio and the logical DPI the window got."""
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)


def qt_widget_classes() -> Iterator[str]:
    """The name of every widget class Qt itself defines, the names it keeps a class's font
    under. They are read from the module by name: PySide makes a class when it is first asked
    for, so the classes already made are only the ones something has used."""
    for name in dir(QtWidgets):
        made = getattr(QtWidgets, name)
        if isinstance(made, type) and issubclass(made, QWidget):
            yield name


def fonts_in_points() -> None:
    """Put the fonts Android's theme gave the application in points, at the same number.

    Qt's Android theme sizes its fonts in pixels, the system's size divided by the screen's
    own ratio (2.625 on a Pixel 8a), whatever ratio Qt draws at: drawn at 3
    (`whole_pixel_ratio`) the same pixel count came out a seventh bigger (the phone's
    `display` line, 2026-11-22: `ratio=3.000 logical_dpi=63.0 font=-1.0pt`, a pixel-sized
    font). A size in points follows the logical DPI, where Qt put the difference: 16 points
    at 63 DPI is 14 of Qt's pixels, 42 of the screen's, what 16 pixels were at 2.625. At a
    ratio that was whole already the DPI is 72, and a point is a pixel.

    Setting the application's font drops the fonts the theme gave single widget classes, so
    those are read first and set again, in points too."""
    def in_points(font: QFont) -> QFont:
        if font.pixelSize() > 0:
            font.setPointSizeF(font.pixelSize())
        return font

    default = QApplication.font()
    of_class = {name: QApplication.font(name) for name in qt_widget_classes()}
    QApplication.setFont(in_points(QFont(default)))
    for name, font in of_class.items():
        if font != default:
            QApplication.setFont(in_points(font), name)


def main() -> None:
    FatalTrace.enabled()  # before Qt: a native crash anywhere after this leaves every thread's stack
    _install_excepthook()
    whole_pixel_ratio()
    # Qt's accessibility bridge is switched off by the APK's activity before Qt's layout
    # exists (tools/android/keepalive ToadActivity.onCreate sets QT_ANDROID_DISABLE_ACCESSIBILITY):
    # Qt reads it from Java while the activity is created, before this Python runs.
    application = FrameProbe.application(sys.argv[:1])
    fonts_in_points()
    session = SessionRecord(time.time())
    application.applicationStateChanged.connect(session.changed)
    memory = SuspendedMemory()
    application.applicationStateChanged.connect(memory.changed)
    scheme = current_scheme(os.environ)
    QtSplash.shown(application, scheme)
    try:
        load_client()(scheme)
    except BaseException as failure:
        session.ended(f"failed {type(failure).__name__}")
        report = traceback.format_exc()
        print(report, file=sys.stderr, flush=True)
        # The APK has no adb on this phone, so the traceback has to leave the device: save
        # it to the state folder and POST it to the dev crash sink on the tailnet. On
        # Qt-for-Android a top-level QMessageBox deadlocks with the compositor during first
        # paint (QAndroidPlatformOpenGLWindow::eglSurface deadlock protector SIGABRT), so
        # we rely on the sink POST and the saved file as the only record of the crash.
        saved_path = paths.save_error(failure, "android_startup")
        from toad.client.host import post_crash_to_sink

        post_crash_to_sink(
            saved_path, "android_startup", f"Toad startup crash: {type(failure).__name__}"
        )
        raise
    session.ended("closed")
