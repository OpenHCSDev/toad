"""Shared comms application host contract, independent of any UI toolkit.

Native applications compose this with their framework base. The host
declares only irreducible native primitives; shared connection, command
and navigation code calls these without importing Textual or Qt.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from formbridge.publications import PublicationStream
from toad.resource_release import ResourceRelease


class CommsHost(ABC):
    """The operations shared comms code needs from the native application."""

    @abstractmethod
    def schedule_ui(self, callback: Callable[[], None]) -> None:
        """Deferred until after the current message; never inline."""

    @abstractmethod
    def repeat_ui(self, seconds: float, callback: Callable[[], None]) -> ResourceRelease:
        """Periodic UI-thread callback; release stops it."""

    @property
    @abstractmethod
    def running_loop(self) -> asyncio.AbstractEventLoop:
        """The native event loop the application runs on."""

    @abstractmethod
    def report_fatal(self, error: Exception) -> None:
        """Record and report through the native failure owner."""

    @abstractmethod
    def show_warning(self, text: str, title: str) -> None:
        """Native warning notice; no Core state change."""

    @abstractmethod
    def show_error(self, error: Exception | str, title: str) -> None:
        """Native error notice with the original exception."""

    @abstractmethod
    def copy_to_clipboard(self, text: str) -> None:
        """Native clipboard effect."""

    @property
    @abstractmethod
    def events(self) -> PublicationStream:
        """The application's event stream for subscribe/publish."""

    @property
    @abstractmethod
    def tab_names(self) -> tuple[str, ...]:
        """The current open tab mode names, for interest change detection."""

    @abstractmethod
    def open_thread_identities(self, root: str) -> set:
        """ThreadIncarnation set for sessions viewing this root."""

    @abstractmethod
    def open_channel_targets(self, root: str) -> set[str]:
        """Channel targets for sessions viewing this root."""

    @abstractmethod
    def retire_views(self, root: Path, retired: object) -> None:
        """Notify the session navigation that views were retired for this root."""

    @property
    @abstractmethod
    def preparation(self) -> object:
        """Work scheduler with run_thread for async preparation tasks."""

    @property
    @abstractmethod
    def sidebar_show_stopped(self) -> bool:
        """Whether the sidebar shows stopped sessions."""

    @property
    @abstractmethod
    def sidebar_show_archived(self) -> bool:
        """Whether the sidebar shows archived sessions."""

    @abstractmethod
    def open_direct_messages(self, target: str) -> None:
        """Navigate to a DM conversation with the named target."""

    @abstractmethod
    def has_session(self, mode: str) -> bool:
        """Whether a session with this mode identifier exists."""

    @abstractmethod
    def close_session(self, mode: str) -> None:
        """Request the session with this mode to close."""

    @property
    @abstractmethod
    def project_dir(self) -> Path | None:
        """The project directory the application was opened on."""
