"""Start the Qt client on a UI profile: `python -m toad.qt.main PROFILE [PROJECT]`."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import qasync
from PySide6.QtWidgets import QApplication

from agent_comms.projects.checkouts import Checkout
from objectstate import set_base_config_type
from ui_theme.catalog import SCHEMES
from ui_theme.scheme import ColourScheme
from ui_theme.wal import WalFile

from toad.client.connection import ProcessRemoteCoreConnection, RemoteCoreConnection
from toad.application_lifetime import ApplicationStart
from toad.qt.window import QtToadApp
from toad.render_backend import Renderer
from toad.render_in_thread import InThreadRenderer
from toad.render_processes import RenderProcessPool
from toad.work_preparation import PreparationRuntime


def _renderer_for_platform(connection: RemoteCoreConnection) -> Renderer:
    """A ProcessPool on hosts that fork, an in-thread renderer on Android's Python."""
    if hasattr(sys, "getandroidapilevel"):
        return InThreadRenderer()
    return RenderProcessPool(connection.helper_start)


@dataclass(frozen=True)
class QtClientSettings:
    """The Qt client's settings root. It holds no settings yet; ObjectState needs one root
    type named for the process before it holds any object, such as a command form's draft.
    Toad's Textual settings root lives in a module that needs Textual."""


def current_scheme(environment: Mapping[str, str]) -> ColourScheme:
    """Toad's default theme: pywal's palette once pywal has written it, else Textual's dark."""
    wal = WalFile.directory(environment) / WalFile.NAME
    return WalFile.read(wal).scheme if wal.is_file() else SCHEMES[0]


async def open_app(connection: RemoteCoreConnection, project: Checkout, scheme: ColourScheme) -> QtToadApp:
    """The Qt client shown over the bus behind ``connection``, its saved tabs read and its
    sidebar observing."""
    set_base_config_type(QtClientSettings)
    app = QtToadApp(connection, project, PreparationRuntime(_renderer_for_platform(connection)), scheme)
    # The loop outlives the window: closing it starts the shared client shutdown, which
    # runs on this loop, so Qt must not stop the loop when the last window closes.
    QApplication.instance().setQuitOnLastWindowClosed(False)
    await (await app.get_db()).create()
    app.start_client()
    await app.wait_operations(ApplicationStart)
    return app


async def serve(connection: RemoteCoreConnection, project: Checkout, scheme: ColourScheme) -> None:
    """Show the bus behind ``connection``: desktop passes the process-decoding member,
    Android the one decoding in place."""
    app = await open_app(connection, project, scheme)
    closed = asyncio.get_running_loop().create_future()
    QApplication.instance().lastWindowClosed.connect(lambda: closed.done() or closed.set_result(None))
    await closed
    await app.close_client()


def main(arguments: list[str] = sys.argv) -> None:
    profile = Path(arguments[1])
    project = Checkout(Path(arguments[2]) if len(arguments) > 2 else Path.home())
    QApplication(arguments[:1])
    qasync.run(serve(ProcessRemoteCoreConnection.read(profile), project, current_scheme(os.environ)))


if __name__ == "__main__":
    main()
