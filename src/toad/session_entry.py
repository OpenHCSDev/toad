"""Declared logical sessions own creation, projection and dependent lifetime.

Entries are the callable factories in WorkspaceSessions, not another roster.
The mounted view remains the authority for source/presentation state.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from agent_comms.display_references import CurrentDisplayReferences, ReferenceContext
from agent_comms.mro_dispatch import handles
from agent_comms.route_selection import RouteSelection
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.ui_model.sidebar import ThreadRowModel

from toad.core.projection import MroProjection
from toad.owner_preparation import ExistingOwnerPlan
from toad.session_scope import SessionScope
from toad.session_tracker import (
    CommsViewKey,
    NamedTab,
    OpenTab,
    SessionDetails,
    ThreadTab,
)

if TYPE_CHECKING:
    from toad.comms_root import Observing
    from toad.screens.main import MainScreen
    from toad.session_navigation import SessionNavigation


class SessionEntry(DeclaredFamily, affix="Entry"):
    def __init__(self, mode: str) -> None:
        self.mode = mode

    @property
    def owner_mode(self) -> str:
        return self.mode

    @abstractmethod
    def __call__(self) -> SessionScope: ...

    def tab(self, sessions: SessionNavigation, observed: Observing) -> OpenTab:
        return self.unobserved_tab()

    @abstractmethod
    def unobserved_tab(self) -> OpenTab: ...

    @property
    @abstractmethod
    def address(self) -> object: ...

    async def ready(self, sessions: SessionNavigation) -> None:
        """Views with deferred loading own their loading completion."""

    async def reconnect(
        self, sessions: SessionNavigation, selected, snapshot, targets
    ) -> None:
        """Only a bound native entry can refresh its connection resource."""

    def source(self, sessions: SessionNavigation) -> MainScreen | None:
        return None

    def thread_row(
        self, sessions: SessionNavigation, row: ThreadRowModel
    ) -> ThreadRowModel:
        """How this entry's own session changes a thread's row; most entries hold none."""
        return row

    def depends_on(self, mode: str) -> bool:
        return self.mode == mode

    def original_threads(
        self, sessions: SessionNavigation
    ) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ()

    def original_channels(self) -> tuple[tuple[str, str], ...]:
        return ()

    def entered(self, previous: str) -> None:
        """Only entries with a return destination retain entry intent."""

    async def return_to(self, sessions: SessionNavigation) -> None:
        await sessions.app.select_session(sessions.app.tab_order.previous(self.mode))

    def forget(self, sessions: SessionNavigation) -> None:
        """End the view's observations before forgetting its logical membership."""
        if view := sessions.app.workspace_sessions.views.get(self.mode):
            view.close_core_events()

    def sync_owner_root(
        self, sessions: SessionNavigation, owner: str, root: str | None
    ) -> None:
        pass

    def sync_project(
        self, sessions: SessionNavigation, owner: str, project: Path
    ) -> None:
        pass


class NativeSessionEntry(SessionEntry):
    def __init__(
        self,
        details: SessionDetails,
        factory: Callable[[], MainScreen],
        original: tuple[str, ThreadIncarnation] | None = None,
    ) -> None:
        super().__init__(details.mode_name)
        self.details = details
        self.factory = factory
        self.original = original

    def original_threads(self, sessions):
        source = self.source(sessions)
        if source is None:
            return (self.original,) if self.original is not None else ()
        return source.thread_identity.transcript_scope().original_threads(
            source.thread_identity
        )

    def __call__(self) -> MainScreen:
        source = self.factory()
        source.session_details = self.details
        source.thread_identity.bind_initial_identity(self.details)
        return source

    @property
    def address(self) -> str:
        return self.mode

    def source(self, sessions: SessionNavigation) -> MainScreen | None:
        return sessions.app.workspace_sessions.views.get(self.mode)

    def thread_row(self, sessions, row):
        """The session this tab opened shows its state on that thread's row."""
        source = self.source(sessions)
        if source is None or all(
            identity != row.incarnation
            for _, identity in self.original_threads(sessions)
        ):
            return row
        return source.session_disposition.present(row, row.disconnected)

    async def reconnect(self, sessions, selected, snapshot, targets):
        if sessions.get(self.mode) is not self or RouteSelection.capture() != selected:
            return
        source = self.source(sessions)
        if source is None:
            return
        original = next(
            (
                identity
                for root, identity in self.original_threads(sessions)
                if Path(root).resolve() == selected.root
                and any(
                    identity.matches_recorded_name(target, snapshot)
                    for target in targets
                )
            ),
            None,
        )
        if original is None:
            return
        thread = snapshot.require(snapshot.canonical_name(original.name))
        binding = thread.execution.owner_binding(snapshot, thread)
        plan = ExistingOwnerPlan.from_binding(binding)
        if plan is None:
            return
        await source.presentation.operational_binding.reconnect_session(source, plan)

    def unobserved_tab(self) -> OpenTab:
        return NamedTab(self.mode, self.details.name.display or "New Session")

    def tab(self, sessions: SessionNavigation, observed: Observing) -> OpenTab:
        source = self.source(sessions)
        if source is None or not source.belongs_to_wire(observed.service.root):
            return self.unobserved_tab()
        row = observed.sidebar.threads.rows.get(source.thread_identity.thread_name())
        originals = self.original_threads(sessions)
        if (
            row is not None
            and originals
            and not any(
                observed.observes(root) and identity == row.incarnation
                for root, identity in originals
            )
        ):
            return self.unobserved_tab()
        if row is not None:
            return ThreadTab(
                self.mode, source.session_disposition.present(row, row.disconnected)
            )
        return self.unobserved_tab()

    async def return_to(self, sessions: SessionNavigation) -> None:
        app = sessions.app
        # Another session is preferred to a file or history tab between them.
        remaining = [
            details.mode_name
            for details in app.session_tracker.ordered_sessions
            if details.mode_name != self.mode
        ]
        await app.select_session(
            app.tab_order.previous(self.mode, eligible=remaining or None)
        )

    def forget(self, sessions: SessionNavigation) -> None:
        super().forget(sessions)
        sessions.app.session_tracker.close_session(self.mode)


class HistorySessionEntry(SessionEntry, MroProjection):
    def __init__(
        self,
        mode: str,
        key: CommsViewKey,
        project: Path,
        owner_root: str | None,
        participants: tuple[ThreadIncarnation, ...],
        owner,
    ) -> None:
        super().__init__(mode)
        self.key, self.project, self.owner_root = key, project, owner_root
        self.participants, self.owner = participants, owner

    @property
    def owner_mode(self) -> str:
        return self.key.owner_mode

    def original_threads(self, sessions):
        return tuple((self.key.root, participant) for participant in self.participants)

    def original_channels(self):
        return self.key.conversation.channels_needed(self.key.root)

    def __call__(self):
        from toad.screens.comms import CommsScreen

        key = self.key
        return CommsScreen(
            project_path=self.project,
            owner_mode=key.owner_mode,
            me=self.owner.thread_identity.thread_name(),
            conversation=key.conversation,
            owner_root=self.owner_root,
            wire_root=key.root,
        )

    @property
    def address(self) -> object:
        return self.key.conversation.view_identity(self.key)

    async def ready(self, sessions: SessionNavigation) -> None:
        await sessions.app.workspace_sessions.require(self.mode).wait_content_ready()

    def source(self, sessions: SessionNavigation) -> MainScreen | None:
        return sessions.source(self.key.owner_mode)

    def unobserved_tab(self) -> OpenTab:
        return NamedTab(self.mode, self.key.conversation.initial_label)

    def tab(self, sessions: SessionNavigation, observed: Observing) -> OpenTab:
        return self.dispatch_sync(observed.references_for(self.key.root), observed)

    @handles(ReferenceContext)
    def preparing_tab(self, references, observed) -> OpenTab:
        return self.unobserved_tab()

    @handles(CurrentDisplayReferences)
    def referenced_tab(self, references, observed) -> OpenTab:
        conversation = self.key.conversation
        return NamedTab(
            self.mode,
            conversation.label(references),
            conversation.unread(observed.sidebar.observation),
        )

    def depends_on(self, mode: str) -> bool:
        return super().depends_on(mode) or self.key.owner_mode == mode

    async def return_to(self, sessions: SessionNavigation) -> None:
        app, owner = sessions.app, self.key.owner_mode
        await app.select_session(
            owner
            if sessions.get(owner) is not None
            else app.tab_order.previous(self.mode)
        )

    def sync_owner_root(
        self, sessions: SessionNavigation, owner: str, root: str | None
    ) -> None:
        self.owner_root = (
            root
            if root is not None
            and Path(root).expanduser().resolve() == Path(self.key.root)
            else None
        )
        if view := sessions.app.workspace_sessions.views.get(self.mode):
            view.rebind_identity(self.owner.thread_identity.thread_name())
            view.rebind_owner_root(self.owner_root)

    def sync_project(
        self, sessions: SessionNavigation, owner: str, project: Path
    ) -> None:
        self.project = project
        if view := sessions.app.workspace_sessions.views.get(self.mode):
            view.rebind_project(project)


class PreviewSessionEntry(SessionEntry):
    """A read-only file in its own tab."""

    def __init__(self, mode: str, path: Path, origin: str) -> None:
        super().__init__(mode)
        self.path, self.origin = path, origin

    @classmethod
    def of(cls, mode: str, path: Path, origin: str) -> PreviewSessionEntry:
        from toad.acp.agent_log import AgentLog

        return (AcpLogSessionEntry if AgentLog.writes(path) else cls)(
            mode, path, origin
        )

    def __call__(self):
        from toad.screens.file_preview import FilePreviewScreen

        return FilePreviewScreen(self.path, self.content)

    def content(self):
        from toad.widgets.project_panel import FilePreview

        return FilePreview(self.path, id="file-preview")

    @property
    def title(self) -> str:
        return self.path.name

    @property
    def address(self) -> Path:
        return self.path

    def unobserved_tab(self) -> OpenTab:
        return NamedTab(self.mode, self.title)

    def entered(self, previous: str) -> None:
        if previous != self.mode:
            self.origin = previous

    async def return_to(self, sessions: SessionNavigation) -> None:
        app = sessions.app
        target = (
            self.origin
            if sessions.get(self.origin) is not None
            else app.tab_order.previous(self.mode)
        )
        await app.select_session(target)


class AcpLogSessionEntry(PreviewSessionEntry):
    """An agent's ACP log in its own tab, named for the agent and start time in the file name."""

    def content(self):
        from toad.widgets.acp_log import AcpLogPreview

        return AcpLogPreview(self.path, id="file-preview")

    @property
    def title(self) -> str:
        return f"ACP log · {self.path.stem}"
