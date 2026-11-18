"""The bus the APK serves: the held profile for the endpoint it was built for, over the
connection that decodes in place. Loaded after the first frame (`toad.qt.android.load_client`)."""

from __future__ import annotations

import time

import qasync
from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.connector import HoldUiVerb
from agent_comms.transport.connector_profile import UiConnectionProfile
from agent_comms.transport.connector_store import ConnectorStore
from ui_theme.scheme import ColourScheme

from toad.client.bus_selection import BusChoice
from toad.client.connection import RemoteCoreConnection
from toad.qt.android_app import APP
from toad.qt.client_start import serve

BUNDLED_PROFILE = APP / "profile.json"


def held_connection() -> RemoteCoreConnection:
    """The bus this APK was built for, as the terminal app opens the connection it was
    launched with: the held profile for the bundled profile's endpoint. Held buses are
    listed by file name, so the first of them was whichever host sorts first (laptop before
    ts-gaming), and a bus the reader once switched to became every later launch's. On first
    start the bundled profile is held the way any given profile is held
    (`agent-comms-connector hold-ui`), so the welcome lists it beside the tailnet's buses and
    a reader can forget it; with it forgotten, the first bus still held opens."""
    if not BusChoice.held(time.time()):
        # The APK unpacks its files readable by the app; a held credential is the app's alone.
        BUNDLED_PROFILE.chmod(0o600)
        HoldUiVerb(profile=BUNDLED_PROFILE).apply(ConnectorStore.owned())
    built_for = UiConnectionProfile.read(BUNDLED_PROFILE).endpoint.url
    held = BusChoice.held(time.time())
    chosen = next((bus for bus in held if bus.profile.profile.endpoint.url == built_for), held[0])
    return RemoteCoreConnection.read(chosen.profile.path)


def serve_held(scheme: ColourScheme) -> None:
    """Serve the held bus until the application ends."""
    qasync.run(serve(held_connection(), Checkout(APP), scheme))
