"""Shared comms application host contract, independent of any UI toolkit.

Native applications compose this with their framework base. The host
declares only irreducible native primitives; shared connection, command
and navigation code calls these without importing Textual or Qt.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Never

from agent_comms.cli_verbs.cli_command import TargetAction
from agent_comms.cli_verbs.target_fields import TargetField
from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.transport.request import CoreAccess
from agent_comms.history_views import RetiredViews
from agent_comms.projects.checkouts import Checkout

from formbridge.operations import OperationKind
from formbridge.publications import PublicationStream
from agent_comms.registry.thread_identity import ThreadIncarnation

from toad.client.session_projection import SessionCollection
from toad.client.tab_identity import TabIdentity
from toad.client.tab_order import TabOrder
from toad.work_preparation import PreparationRuntime


class CommandOrigin(ABC):
    """Captured native presentation owner for off-loop command preparation.

    Captured before the preparation worker starts. current() answers
    whether the view/screen is still selected and live when the reply
    arrives. edit() runs the native dialog, returning the argument
    mapping or None on cancellation.
    """

    @abstractmethod
    def current(self) -> bool:
        """Whether the captured view/screen is still selected and live."""

    @abstractmethod
    async def edit(self, definition: TargetAction, title: str, fields: tuple[TargetField, ...],
                   core: CoreAccess) -> dict[str, str | None] | None:
        """Run the native dialog. Returns arguments or None on cancel."""


class CommsHost:
    """The operations shared comms code needs from the native application."""

    events: PublicationStream
    preparation: PreparationRuntime
    project_dir: Checkout

    def succeed_onto(self, runtime: LaunchRuntime) -> Never:
        """Hand this process to another runtime; never returns."""
        raise NotImplementedError

    def schedule_ui(self, callback: Callable[[], None]) -> None:
        """Deferred until after the current message; never inline."""
        raise NotImplementedError

    def repeat_ui(self, seconds: float, callback: Callable[[], None]) -> object:
        """Periodic UI-thread callback; the returned handle's stop() ends it."""
        raise NotImplementedError

    def delay_ui(self, seconds: float, callback: Callable[[], None]) -> None:
        """One UI-thread callback after this many seconds."""
        raise NotImplementedError

    def run_operation(self, kind: type[OperationKind], task: Callable[[], Awaitable[None]]) -> None:
        """Start one operation of this kind; an exclusive kind's newer start cancels the running one."""
        raise NotImplementedError

    def cancel_operations(self, kind: type[OperationKind]) -> None:
        """Cancel every running operation of this kind."""
        raise NotImplementedError

    async def end_operations(self) -> None:
        """Cancel every running operation and wait for each to finish unwinding, so none
        runs on while the application closes the views and readers it uses."""
        raise NotImplementedError

    async def wait_operations(self, kind: type[OperationKind]) -> None:
        """Wait until every running operation of this kind has finished; an operation's
        failure is reported through the native failure owner, not raised here."""
        raise NotImplementedError

    @property
    def running_loop(self) -> asyncio.AbstractEventLoop:
        """The native event loop the application runs on."""
        raise NotImplementedError

    def report_fatal(self, error: Exception) -> None:
        """Record and report through the native failure owner."""
        raise NotImplementedError

    def show_info(self, text: str, title: str) -> None:
        """Native information notice; no Core state change."""
        raise NotImplementedError

    def show_warning(self, text: str, title: str) -> None:
        """Native warning notice of plain text; no Core state change."""
        raise NotImplementedError

    def show_error(self, error: Exception | str, title: str) -> None:
        """Native error notice with the original exception."""
        raise NotImplementedError

    def log_error(self, text: str) -> None:
        """Write to the native error log; the user is not interrupted."""
        raise NotImplementedError

    def copy_to_clipboard(self, text: str) -> None:
        """Native clipboard effect."""
        raise NotImplementedError

    def clear_focus(self) -> None:
        """Take keyboard focus off every control, so a focused editor sends its value."""
        raise NotImplementedError

    async def reveal_sidebar(self) -> bool:
        """Show and focus the session sidebar of the current view; False when it has none."""
        raise NotImplementedError

    def capture_command_origin(self) -> CommandOrigin:
        """The view a command starts on, captured before its fields are prepared off the loop."""
        raise NotImplementedError

    @property
    def application_running(self) -> bool:
        """Whether the native application is running and not yet closing."""
        raise NotImplementedError

    @property
    def display_size(self) -> tuple[int, int]:
        """The application's display width and height, as usage reports count them."""
        raise NotImplementedError

    def end_application(self) -> None:
        """End the native application."""
        raise NotImplementedError

    @property
    def tab_names(self) -> tuple[TabIdentity, ...]:
        """The current open tab mode names, for interest change detection."""
        raise NotImplementedError

    def open_thread_identities(self, root: str) -> set:
        """ThreadIncarnation set for sessions viewing this root."""
        raise NotImplementedError

    def open_channel_targets(self, root: str) -> set[str]:
        """Channel targets for sessions viewing this root."""
        raise NotImplementedError

    def retire_views(self, root: Path, retired: RetiredViews) -> None:
        """Notify the session navigation that views were retired for this root."""
        raise NotImplementedError

    @property
    def sidebar_show_stopped(self) -> bool:
        """Whether the sidebar shows stopped sessions."""
        raise NotImplementedError

    @property
    def sidebar_show_archived(self) -> bool:
        """Whether the sidebar shows archived sessions."""
        raise NotImplementedError

    def open_direct_messages(self, target: str) -> None:
        """Navigate to a DM conversation with the named target."""
        raise NotImplementedError

    def has_session(self, mode: str) -> bool:
        """Whether a session with this mode identifier exists."""
        raise NotImplementedError

    def close_session(self, mode: str) -> None:
        """Request the session with this mode to close."""
        raise NotImplementedError


class NavigatingHost[Source](CommsHost):
    """A host with Toad's tabs and session navigation: which tabs are open, which threads
    and channels their views were opened over, and retiring views a bus retired."""

    tab_order: TabOrder
    session_navigation: SessionCollection[Source]

    @property
    def tab_names(self) -> tuple[TabIdentity, ...]:
        return self.tab_order.names

    def open_thread_identities(self, root: str) -> set[ThreadIncarnation]:
        return {identity for member in self.session_navigation.members
                for owner, identity in member.original_threads(self.session_navigation)
                if owner == root}

    def open_channel_targets(self, root: str) -> set[str]:
        return {target for member in self.session_navigation.members
                for owner, target in member.original_channels() if owner == root}

    def retire_views(self, root: Path, retired: RetiredViews) -> None:
        self.session_navigation.views_retired(root, retired)
