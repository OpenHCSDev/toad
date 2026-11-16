"""Start the Qt client on a UI profile: `python -m toad.qt.main PROFILE [PROJECT]`."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from pathlib import Path

import qasync
from PySide6.QtWidgets import QApplication

from agent_comms.projects.checkouts import Checkout
from ui_theme.catalog import SCHEMES
from ui_theme.scheme import ColourScheme
from ui_theme.wal import WalFile

from toad.client.connection import (
    CoordinationAccess,
    ProcessRemoteCoreConnection,
    RemoteCoreConnection,
)
from toad.qt.host import QtCommsHost
from toad.qt.window import CommsWindow
from toad.render_processes import RenderProcessPool
from toad.work_preparation import PreparationRuntime


def current_scheme(environment: Mapping[str, str]) -> ColourScheme:
    """Toad's default theme: pywal's palette once pywal has written it, else Textual's dark."""
    wal = WalFile.directory(environment) / WalFile.NAME
    return WalFile.read(wal).scheme if wal.is_file() else SCHEMES[0]


async def serve(connection: RemoteCoreConnection, project: Checkout, scheme: ColourScheme) -> None:
    """Show the bus behind ``connection``: desktop passes the process-decoding member,
    Android the one decoding in place."""
    host = QtCommsHost(project, PreparationRuntime(RenderProcessPool(connection.helper_start)))
    access = CoordinationAccess(host, connection)
    window = CommsWindow(access, scheme)
    window.resize(420, 820)
    window.show()
    access.open_current().show_sidebar(window.threads)
    closed = asyncio.get_running_loop().create_future()
    QApplication.instance().lastWindowClosed.connect(lambda: closed.done() or closed.set_result(None))
    await closed


def main(arguments: list[str] = sys.argv) -> None:
    profile = Path(arguments[1])
    project = Checkout(Path(arguments[2]) if len(arguments) > 2 else Path.home())
    QApplication(arguments[:1])
    qasync.run(serve(ProcessRemoteCoreConnection.read(profile), project, current_scheme(os.environ)))


if __name__ == "__main__":
    main()
