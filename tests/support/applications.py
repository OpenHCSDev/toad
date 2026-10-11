"""Helpers for a test that subclasses the application."""

from __future__ import annotations

import inspect
from pathlib import Path


def stylesheet_of_application() -> list[Path]:
    """The installed application's stylesheets as absolute paths.

    Textual resolves a relative ``CSS_PATH`` against the file that defines the
    class, so a subclass defined in a test needs these set explicitly.
    """
    from toad.app import ToadApp

    directory = Path(inspect.getfile(ToadApp)).parent
    return [directory / name for name in ToadApp.CSS_PATH]


def record_notifications(app) -> None:
    """Let the headless app keep its notifications (Textual drops them under test by default)."""
    app._disable_notifications = False
