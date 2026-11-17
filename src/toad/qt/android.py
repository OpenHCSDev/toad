"""The APK's start: Toad's Qt client on this phone, on the first bus it holds.

The APK's `main.py` (tools/android/main.py) enters the APK's environment
(toad.qt.android_app) and then runs `main` here.

The APK's activity (tools/android/keepalive) holds the process in the foreground with an
ongoing notification, so switching away leaves Toad running; once suspended, the app
gives the memory it can rebuild back to Android (SuspendedMemory).

A failure before the window opens is shown on screen, since a phone without adb has nowhere
else to show it. So is a cold start's cause: SessionRecord notes each state Android moves the
app through, and the next start says how the last session ended.
"""

import ctypes
import gc
import os
import sys
import threading
import time
import traceback

import qasync
from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.connector import HoldUiVerb
from agent_comms.transport.connector_store import ConnectorStore
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication, QMessageBox

from toad import paths
from toad.client.bus_selection import BusChoice
from toad.client.connection import RemoteCoreConnection
from toad.qt.android_app import APP
from toad.client.host import post_crash_to_sink
from toad.qt.main import current_scheme, serve

BUNDLED_PROFILE = APP / "profile.json"


def held_connection() -> RemoteCoreConnection:
    """The first bus this phone holds. On first start that is the bundled profile, held the
    way any given profile is held (`agent-comms-connector hold-ui`), so the welcome lists it
    beside the tailnet's buses and a reader can forget it."""
    if not BusChoice.held(time.time()):
        # The APK unpacks its files readable by the app; a held credential is the app's alone.
        BUNDLED_PROFILE.chmod(0o600)
        HoldUiVerb(profile=BUNDLED_PROFILE).apply(ConnectorStore.owned())
    return RemoteCoreConnection.read(BusChoice.held(time.time())[0].profile.path)


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

    PATH = APP / "state" / "android-lifecycle.log"

    def __init__(self, now: float) -> None:
        self.previous = self.PATH.read_text().splitlines() if self.PATH.is_file() else []
        self.PATH.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.PATH.open("w", buffering=1)
        self.write(now, "started")
        self.shown: QMessageBox | None = None

    def write(self, when: float, event: str) -> None:
        self.log.write(f"{when:.0f} {event}\n")

    def changed(self, state: Qt.ApplicationState) -> None:
        self.write(time.time(), state.name)
        if state is Qt.ApplicationState.ApplicationActive and self.shown is None and (report := self.report()):
            # The dialog is a top-level QWindow and allocating its EGL surface during
            # ApplicationActive races Android's accessibility probe for the eglSurface()
            # mutex (SIGABRT, QAndroidPlatformOpenGLWindow::eglSurface deadlock protector).
            # Deferring past first-paint lets the probe release before we add a second
            # surface — otherwise every crash seeds the next via this dialog.
            self.shown = QMessageBox(QMessageBox.Icon.Information, "How the last session ended", report)
            self.shown.setModal(False)
            QTimer.singleShot(2000, self.shown.show)

    def ended(self, how: str) -> None:
        self.write(time.time(), how)

    def report(self) -> str | None:
        """None when the last run closed its window, or there was none."""
        if not self.previous or self.previous[-1].endswith(" closed"):
            return None
        stamp, state = self.previous[-1].split(" ", 1)
        since = time.strftime("%H:%M", time.localtime(int(stamp)))
        lines = "\n".join(self.previous[-6:])
        return (f"The last session ended without its window closing; its last record is {state}, "
                f"at {since}. After ApplicationSuspended or ApplicationHidden, Android ended the "
                f"process in the background; after ApplicationActive, it crashed in use.\n\n"
                f"Its last records:\n{lines}")


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
            threading.Thread(
                target=post_crash_to_sink,
                args=(saved_path, "android_uncaught", f"Toad uncaught: {kind.__name__}"),
                daemon=True,
            ).start()
        except BaseException:  # the hook must not raise, or Python's default handler aborts
            pass
        previous(kind, value, tb)

    sys.excepthook = hook


def main() -> None:
    _install_excepthook()
    # Qt-for-Android's accessibility bridge (QtAndroidAccessibility::runInObjectContext)
    # holds the EGL deadlock-protector mutex at the same time the main loop tries to
    # acquire it for QAndroidPlatformOpenGLWindow::eglSurface() during first paint
    # flush, so the protector aborts (SIGABRT). Pixel 8a's accessibility service
    # probes the window on launcher-tap even with TalkBack off — enough to engage
    # the bridge in the critical window. Toad has no accessibility consumers; drop
    # the bridge before QApplication binds it.
    os.environ.setdefault("QT_ANDROID_DISABLE_ACCESSIBILITY", "1")
    os.environ.setdefault("QT_ACCESSIBILITY", "0")
    os.environ.setdefault(
        "QT_LOGGING_RULES",
        "qt.qpa.*=true;qt.qpa.backingstore=true;qt.qpa.gl=true;qt.qpa.androidsurface=true",
    )
    application = QApplication(sys.argv[:1])
    # The env vars alone don't stop Qt's Java-side accessibility bridge — the
    # protector still trips with runInObjectContext as the lock holder. Shut the
    # API-side framework off too: setActive(False) tells Qt to answer "no
    # accessibility" to Android's probes. A Python lambda can't substitute for
    # the C function pointer installFactory expects — Shiboken NULL-derefs when
    # it tries to introspect one, so don't install a factory at all.
    try:
        QAccessible.setActive(False)
    except Exception:
        pass
    session = SessionRecord(time.time())
    application.applicationStateChanged.connect(session.changed)
    memory = SuspendedMemory()
    application.applicationStateChanged.connect(memory.changed)
    try:
        qasync.run(serve(held_connection(), Checkout(APP), current_scheme(os.environ)))
    except BaseException as failure:
        session.ended(f"failed {type(failure).__name__}")
        report = traceback.format_exc()
        print(report, file=sys.stderr, flush=True)
        # The APK has no adb on this phone, so the traceback has to leave the device: save
        # it to the state folder and POST it to the dev crash sink on the tailnet. Daemon
        # thread so the modal is not blocked when the network is slow. The modal also stays
        # open while this runs, since the sink POST can take a couple of seconds.
        saved_path = paths.save_error(failure, "android_startup")
        threading.Thread(
            target=post_crash_to_sink,
            args=(saved_path, "android_startup", f"Toad startup crash: {type(failure).__name__}"),
            daemon=True,
        ).start()
        QMessageBox(QMessageBox.Icon.Critical, "Toad could not start", report[-3000:]).exec()
        raise
    session.ended("closed")
