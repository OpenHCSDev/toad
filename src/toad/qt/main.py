"""Start the Qt client on a UI profile: `python -m toad.qt.main PROFILE [PROJECT]`.

This module is the desktop entry and imports only what Qt's first frame needs: the frame is
painted (`QtSplash`), then the client loads and serves (`toad.qt.client_start`)."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from toad.qt.splash import QtSplash
from toad.qt.theme import current_scheme


def main(arguments: list[str] = sys.argv) -> None:
    application = QApplication(arguments[:1])
    scheme = current_scheme(os.environ)
    QtSplash.shown(application, scheme)
    # The client loads once the first frame is up: importing it is most of a start.
    from toad.qt.client_start import serve_profile

    serve_profile(arguments, scheme)


if __name__ == "__main__":
    main()
