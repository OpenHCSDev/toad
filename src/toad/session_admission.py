"""Declared logical sessions own creation, projection and dependent lifetime.

Admissions are the callable factories in WorkspaceSessions, not another roster.
The mounted view remains the authority for source/presentation state.
"""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from agent_comms.comms import wire
from agent_comms.thread_identity import ThreadIncarnation

from toad.conversation_kind import ConversationKind
from toad.session_tracker import CommsViewKey, ExactUnread, OpenTab, SessionDetails, UnreadPresentation

if TYPE_CHECKING:
    from toad.session_navigation import SessionAdmissions
    from toad.screens.main import MainScreen
    from toad.screens.session_view import SessionView


class SessionAdmission(DeclaredFamily, affix="Admission"):
    def __init__(self, mode: str) -> None:
        self.mode = mode

    @abstractmethod
    def __call__(self) -> SessionView: ...

    @abstractmethod
    def tab(self, sessions: SessionAdmissions, snapshot) -> OpenTab: ...

    @property
    @abstractmethod
    def address(self) -> object: ...

    async def ready(self, sessions: SessionAdmissions) -> None:
        """Views with deferred loading own their admission completion."""

    async def reconnect(self, sessions: SessionAdmissions, selected, snapshot, targets) -> None:
        """Only a bound native admission can refresh its connection resource."""

    def source(self, sessions: SessionAdmissions) -> MainScreen | None:
        return None

    def accepts_launch(self, sessions: SessionAdmissions, agent_identity: str, session_id: str) -> bool:
        return False

    def depends_on(self, mode: str) -> bool:
        return self.mode == mode

    def original_threads(self, sessions: SessionAdmissions) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ()

    def original_channels(self) -> tuple[tuple[str, str], ...]:
        return ()

    def entered(self, previous: str) -> None:
        """Only admissions with a return destination retain entry intent."""

    async def return_to(self, sessions: SessionAdmissions) -> None:
        await sessions.app.select_session(sessions.app.tab_order.previous(self.mode))

    def forget(self, sessions: SessionAdmissions) -> None:
        """Release any domain membership beyond the workspace factory itself."""

    def sync_identity(self, sessions: SessionAdmissions, owner: str, previous: str, current: str) -> None:
        pass

    def sync_recovery(self, sessions: SessionAdmissions, owner: str, root: str | None) -> None:
        pass

    def sync_project(self, sessions: SessionAdmissions, owner: str, project: Path) -> None:
        pass


class NativeSessionAdmission(SessionAdmission):
    def __init__(self, details: SessionDetails, factory: Callable[[], MainScreen],
                 original: tuple[str, ThreadIncarnation] | None = None) -> None:
        super().__init__(details.mode_name)
        self.details = details
        self.factory = factory
        self.original = original

    def original_threads(self, sessions):
        source = self.source(sessions)
        fact = sessions.app.coordination_facts.get(source) if source is not None else None
        if fact is not None:
            return ((fact.wire_root, fact.thread),)
        return (self.original,) if self.original is not None else ()

    def __call__(self) -> MainScreen:
        source = self.factory()
        self.details.bind_initial_identity(source._agent_session_id)
        return source

    @property
    def address(self) -> str:
        return self.mode

    def source(self, sessions: SessionAdmissions) -> MainScreen | None:
        return sessions.app.workspace_sessions.views.get(self.mode)

    async def reconnect(self, sessions, selected, snapshot, targets):
        from toad.comms_root import RouteSelection

        if sessions.get(self.mode) is not self or RouteSelection.capture() != selected:
            return
        if source := self.source(sessions):
            if agent := source.conversation.agent:
                if binding := agent.coordination:
                    if ((binding.wire_root, binding.thread) in self.original_threads(sessions)
                            and Path(binding.wire_root).resolve() == selected.root
                            and any(binding.thread.matches_recorded_name(target, snapshot)
                                    for target in targets)):
                        await agent.session.reconnect()

    def accepts_launch(self, sessions: SessionAdmissions, agent_identity: str, session_id: str) -> bool:
        source = self.source(sessions)
        if source is None or not source.has_agent():
            return False
        if source._agent.identity != agent_identity:
            return False
        live = source.conversation.agent
        if session_id in {source._agent_session_id, live.session_id if live else None}:
            return True
        root = source.coordination_root
        return root is not None and wire(root).registry.canonical_name(session_id) == source._session_thread

    def tab(self, sessions: SessionAdmissions, snapshot) -> OpenTab:
        source = self.source(sessions)
        name = source._comms_thread if source else ""
        presentation = next((thread.presentation for thread in snapshot.threads
                             if thread.thread.name == name), None) if snapshot else None
        return OpenTab(self.mode, presentation.label if presentation else self.details.title or "New Session",
                       UnreadPresentation.for_thread(snapshot, name) if snapshot else ExactUnread())

    async def return_to(self, sessions: SessionAdmissions) -> None:
        app = sessions.app
        remaining = [details.mode_name for details in app.session_tracker.ordered_sessions
                     if details.mode_name != self.mode]
        if remaining:
            await app.select_session(app.tab_order.previous(self.mode, eligible=remaining))
            return
        source = self.source(sessions)
        if source is not None and source.has_agent():
            await sessions.new(source.spawn)
        else:
            await app.select_session("store")

    def forget(self, sessions: SessionAdmissions) -> None:
        sessions.app.session_tracker.close_session(self.mode)


class HistorySessionAdmission(SessionAdmission):
    def __init__(self, mode: str, key: CommsViewKey, kind: type[ConversationKind], project: Path,
                 recovery_root: str | None, participants: tuple[ThreadIncarnation, ...]) -> None:
        super().__init__(mode)
        self.key, self.kind, self.project, self.recovery_root = key, kind, project, recovery_root
        self.participants = participants

    def original_threads(self, sessions):
        return tuple((self.key.root, participant) for participant in self.participants)

    def original_channels(self):
        return self.kind.admitted_channels(self.key.root, self.key.target)

    def __call__(self):
        from toad.screens.comms import CommsScreen
        key = self.key
        return CommsScreen(project_path=self.project, owner_mode=key.owner_mode, me=key.me,
                           target=key.target, kind=self.kind,
                           recovery_root=self.recovery_root, wire_root=key.root)

    @property
    def address(self) -> object:
        return self.kind.view_identity(self.key)

    async def ready(self, sessions: SessionAdmissions) -> None:
        await sessions.app.workspace_sessions.require(self.mode).wait_content_ready()

    def source(self, sessions: SessionAdmissions) -> MainScreen | None:
        return sessions.source(self.key.owner_mode)

    def tab(self, sessions: SessionAdmissions, snapshot) -> OpenTab:
        return OpenTab(self.mode, self.key.title, self.kind.unread(snapshot, self.key.target))

    def depends_on(self, mode: str) -> bool:
        return super().depends_on(mode) or self.key.owner_mode == mode

    async def return_to(self, sessions: SessionAdmissions) -> None:
        owner = self.key.owner_mode
        await sessions.app.select_session(owner if owner in sessions.app.workspace_sessions.factories else "store")

    def sync_identity(self, sessions: SessionAdmissions, owner: str, previous: str, current: str) -> None:
        if self.key.owner_mode != owner:
            return
        if self.key.me != previous and wire(self.key.root).registry.canonical_name(self.key.me) != current:
            return
        self.key = replace(self.key, me=current)
        if view := sessions.app.workspace_sessions.views.get(self.mode):
            view.rebind_identity(current)

    def sync_recovery(self, sessions: SessionAdmissions, owner: str, root: str | None) -> None:
        if self.key.owner_mode != owner:
            return
        self.recovery_root = root if root is not None and Path(root).expanduser().resolve() == Path(self.key.root) else None
        if view := sessions.app.workspace_sessions.views.get(self.mode):
            view.rebind_recovery(self.recovery_root)

    def sync_project(self, sessions: SessionAdmissions, owner: str, project: Path) -> None:
        if self.key.owner_mode != owner:
            return
        self.project = project
        if view := sessions.app.workspace_sessions.views.get(self.mode):
            view.rebind_project(project)


class PreviewSessionAdmission(SessionAdmission):
    def __init__(self, mode: str, path: Path, origin: str) -> None:
        super().__init__(mode)
        self.path, self.origin = path, origin

    def __call__(self):
        from toad.screens.file_preview import FilePreviewScreen
        return FilePreviewScreen(self.path)

    @property
    def address(self) -> Path:
        return self.path

    def tab(self, sessions: SessionAdmissions, snapshot) -> OpenTab:
        return OpenTab(self.mode, self.path.name)

    def entered(self, previous: str) -> None:
        if previous != self.mode:
            self.origin = previous

    async def return_to(self, sessions: SessionAdmissions) -> None:
        app = sessions.app
        target = self.origin if self.origin in app.workspace_sessions.factories else app.tab_order.previous(self.mode)
        await app.select_session(target)
