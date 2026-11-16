"""Shared comms application host contract, independent of any UI toolkit.

Native applications compose this with their framework base. The host
declares only irreducible native primitives; shared connection, command
and navigation code calls these without importing Textual or Qt.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Never

from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.history_views import RetiredViews
from agent_comms.projects.checkouts import Checkout

from formbridge.operations import OperationKind
from formbridge.publications import PublicationStream
from agent_comms.registry.thread_identity import ThreadIncarnation

from toad.client.session_projection import SessionCollection
from toad.client.tab_identity import TabIdentity
from toad.client.tab_order import TabOrder
from toad.work_preparation import PreparationRuntime


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

    def run_operation(self, kind: type[OperationKind], task: Callable[[], Awaitable[None]]) -> None:
        """Start one operation of this kind; an exclusive kind's newer start cancels the running one."""
        raise NotImplementedError

    def cancel_operations(self, kind: type[OperationKind]) -> None:
        """Cancel every running operation of this kind."""
        raise NotImplementedError

    @property
    def running_loop(self) -> asyncio.AbstractEventLoop:
        """The native event loop the application runs on."""
        raise NotImplementedError

    def report_fatal(self, error: Exception) -> None:
        """Record and report through the native failure owner."""
        raise NotImplementedError

    def show_warning(self, text: str, title: str) -> None:
        """Native warning notice; no Core state change."""
        raise NotImplementedError

    def show_error(self, error: Exception | str, title: str) -> None:
        """Native error notice with the original exception."""
        raise NotImplementedError

    def copy_to_clipboard(self, text: str) -> None:
        """Native clipboard effect."""
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
