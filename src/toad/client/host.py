"""Shared comms application host contract, independent of any UI toolkit.

Native applications compose this with their framework base. The host
declares only irreducible native primitives; shared connection, command
and navigation code calls these without importing Textual or Qt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class CommsHost(ABC):
    """The operations shared comms code needs from the native application."""

    @abstractmethod
    def schedule_ui(self, callback: Callable[[], None]) -> None:
        """Deferred until after the current message; never inline."""

    @abstractmethod
    def report_fatal(self, error: Exception) -> None:
        """Record and report through the native failure owner."""

    @abstractmethod
    def show_warning(self, text: str, title: str) -> None:
        """Native warning notice; no Core state change."""

    @abstractmethod
    def copy_to_clipboard(self, text: str) -> None:
        """Native clipboard effect."""
