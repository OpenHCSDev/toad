"""Helpers for a test that subclasses the application."""

from __future__ import annotations


def record_notifications(app) -> None:
    """Let the headless app keep its notifications (Textual drops them under test by default)."""
    app._disable_notifications = False
