"""The APK's start: Toad's Qt client on this phone, on the first bus it holds.

The APK's `main.py` is one import of this module (tools/android/main.py), and the app folder
it ships is laid out by tools/android/assemble.py: this package at its root, beside the
files read below. The environment is set before anything imports the libraries that read
it, which is why it sits above the imports:

- the compiled speedups of aiohttp, multidict, yarl, frozenlist and propcache are not
  shipped, so each runs its pure-Python implementation;
- Python's ssl looks for /etc/ssl/cert.pem, which Android lacks (and Android's own store is
  named by OpenSSL's old subject hash), so the app carries certifi's CA bundle;
- Toad's default theme is pywal's palette, and the app carries the desktop's colors.json;
- Toad's database (saved tabs) and the held bus profiles, which agent-comms keeps under the
  home directory, live in the app's own storage.

A failure before the window opens is shown on screen, since a phone without adb has nowhere
else to show it. So is a cold start's cause: SessionRecord notes each state Android moves the
app through, and the next start says how the last session ended.
"""

import os
import sys
import time
import traceback
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
for speedup in ("AIOHTTP", "MULTIDICT", "YARL", "FROZENLIST", "PROPCACHE"):
    os.environ[f"{speedup}_NO_EXTENSIONS"] = "1"
os.environ["SSL_CERT_FILE"] = str(APP / "cacert.pem")
os.environ["PYWAL_CACHE_DIR"] = str(APP / "wal")
os.environ["XDG_STATE_HOME"] = str(APP / "state")
os.environ["HOME"] = str(APP / "home")

import qasync
from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.connector import HoldUiVerb
from agent_comms.transport.connector_store import ConnectorStore
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from toad.client.bus_selection import BusChoice
from toad.client.connection import RemoteCoreConnection
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
            self.shown = QMessageBox(QMessageBox.Icon.Information, "How the last session ended", report)
            self.shown.setModal(False)
            self.shown.show()

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


def main() -> None:
    application = QApplication(sys.argv[:1])
    session = SessionRecord(time.time())
    application.applicationStateChanged.connect(session.changed)
    try:
        qasync.run(serve(held_connection(), Checkout(APP), current_scheme(os.environ)))
    except BaseException as failure:
        session.ended(f"failed {type(failure).__name__}")
        report = traceback.format_exc()
        print(report, file=sys.stderr, flush=True)
        QMessageBox(QMessageBox.Icon.Critical, "Toad could not start", report[-3000:]).exec()
        raise
    session.ended("closed")
