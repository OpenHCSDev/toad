"""Start the Qt client on the Core its arguments select, as Toad's terminal launch does:
`python -m toad.qt.main [--comms-profile PROFILE | --comms-root ROOT] [PROJECT] [--agent NAME]`.

This module is the desktop entry and imports only what Qt's first frame needs: the frame is
painted (`QtSplash`), then the client loads and serves (`toad.qt.client_start`)."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from toad.fatal_trace import FatalTrace
from toad.qt.frame_probe import FrameProbe
from toad.qt.splash import QtSplash
from toad.qt.theme import current_scheme


def main(arguments: list[str] = sys.argv) -> None:
    FatalTrace.enabled()  # before Qt: a native crash anywhere after this leaves every thread's stack
    application = FrameProbe.application(arguments[:1])
    scheme = current_scheme(os.environ)
    QtSplash.shown(application, scheme)
    # The client loads once the first frame is up: importing it is most of a start. The
    # desktop selects its Core as Toad's terminal launch does (`select_connection`: a UI
    # profile reaches Core through its connector, otherwise this machine's bus, under which
    # agents start); Android's start is always remote and never loads `local_connection`.
    from toad.client.local_connection import select_connection
    from toad.qt.client_start import serve_launch

    own = arguments[1:]
    serve_launch(select_connection(own), own, scheme)


if __name__ == "__main__":
    main()
