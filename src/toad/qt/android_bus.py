"""The bus the APK serves: the held profile for the endpoint it was built for. Loaded after
the first frame (`toad.qt.android.load_client`)."""

from __future__ import annotations

import time

from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.connector_profile import UiConnectionProfile
from ui_theme.scheme import ColourScheme

from toad.client.bus_selection import BusChoice, held_profile_path, hold_ui_profile
from toad.client.connection import RemoteCoreConnection
from toad.qt.android_app import APP
from toad.qt.client_start import run_qt_loop, serve

BUNDLED_PROFILE = APP / "profile.json"


def held_connection() -> RemoteCoreConnection:
    """The bus this APK was built for, as the terminal app opens the connection it was
    launched with: the held profile for the bundled profile's endpoint. Held buses are
    listed by file name, so the first of them was whichever host sorts first (laptop before
    ts-gaming), and a bus the reader once switched to became every later launch's. On first
    start the bundled profile is held the way any given profile is held
    (`agent-comms-connector hold-ui`), so the welcome lists it beside the tailnet's buses and
    a reader can forget it; with it forgotten, the first bus still held opens.

    If every held profile has expired (including the bundled one), skip re-holding an
    already-expired bundled profile and open the bundled profile directly so the window
    reaches the sidebar/bus picker instead of crashing on FileExistsError or IndexError.
    """
    # The APK unpacks its files readable by the app; a held credential is the app's alone.
    BUNDLED_PROFILE.chmod(0o600)
    bundled = UiConnectionProfile.read(BUNDLED_PROFILE)
    now = time.time()
    if not BusChoice.held(now) and bundled.credential.expires_at > now:
        if not held_profile_path(bundled).exists():
            hold_ui_profile(bundled)
    held = BusChoice.held(now)
    if not held:
        return RemoteCoreConnection.read(BUNDLED_PROFILE)
    chosen = next(
        (bus for bus in held if bus.profile.profile.endpoint.url == bundled.endpoint.url),
        held[0],
    )
    return RemoteCoreConnection.read(chosen.profile.path)


def serve_held(scheme: ColourScheme) -> None:
    """Serve the held bus until the application ends."""
    run_qt_loop(serve(held_connection(), Checkout(APP), scheme))
