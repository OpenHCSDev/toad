"""Declared logical sessions own identity, projection, ownership and dependent lifetime.

Entries are the callable factories in WorkspaceSessions, not another roster. The
mounted view remains the authority for source/presentation state. A frontend's
member of each entry adds only the view it builds, and is selected through that
frontend's SessionEntries family by the tab identity it shows.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from pathlib import Path

from agent_comms.projects.checkouts import Checkout
from agent_comms.ui_model.sidebar import ThreadRowModel

from toad.client.connection import Observing
from toad.client.session_projection import SessionProjection
from toad.client.session_scope import SessionScope
from toad.client.session_tracker import NamedTab, OpenTab, SessionDetails, ThreadTab
from toad.client.tab_identity import TabIdentity
from toad.launch_binding import AgentBinding
from toad.owner_preparation import ExistingOwnerPlan
from toad.session_host import SessionNavigator

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.registry.thread_identity import ThreadIncarnation


class SessionEntry(DeclaredFamily, SessionProjection[SessionNavigator, Observing], affix="Entry"):
    """Logical session identity, ownership, dependencies and Toad's tab history; a
    frontend's member adds the view it builds through its DeclaredViews family."""

    def __init__(self, identity: TabIdentity) -> None:
        self.identity = identity

    @property
    def mode(self) -> str:
        return self.identity.mode_name

    @property
    def owner_mode(self) -> str:
        return self.mode

    @abstractmethod
    def __call__(self, sessions: SessionNavigator) -> SessionScope:
        """The native view of this tab, built from the navigation that opened it."""

    @property
    @abstractmethod
    def address(self) -> object: ...

    async def ready(self, sessions: SessionNavigator) -> None:
        """Views with deferred loading own their loading completion."""

    async def reconnect(self, sessions: SessionNavigator, selected, snapshot, targets) -> None:
        """Only a bound native entry can refresh its connection resource."""

    def source(self, sessions: SessionNavigator) -> SessionScope | None:
        return None

    def thread_row(self, sessions: SessionNavigator, row: ThreadRowModel) -> ThreadRowModel:
        return row

    def depends_on(self, mode: str) -> bool:
        return self.mode == mode

    def original_channels(self) -> tuple[tuple[str, str], ...]:
        return ()

    def original_threads(self, sessions: SessionNavigator) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ()

    async def return_to(self, sessions: SessionNavigator) -> None:
        """Back to the tab selected before this one; the visit history owns that."""
        await sessions.app.select_session(sessions.app.tab_order.came_from(self.identity))

    def forget(self, sessions: SessionNavigator) -> None:
        """End the view's observations before forgetting its logical membership."""
        if view := sessions.app.workspace_sessions.views.get(self.mode):
            view.close_core_events()


class NativeSessionEntry(SessionEntry):
    def __init__(
        self,
        details: SessionDetails,
        factory: Callable[[], SessionScope],
        original: tuple[str, ThreadIncarnation] | None = None,
    ) -> None:
        super().__init__(details.identity)
        self.details = details
        self.factory = factory
        self.original = original

    @staticmethod
    @abstractmethod
    def session_view(
        project: Checkout,
        binding: AgentBinding,
        *,
        session_pk: int,
        initial_prompt: str | None = None,
    ) -> SessionScope:
        """The frontend's view of an agent session saved as `session_pk`."""

    def original_threads(self, sessions):
        source = self.source(sessions)
        if source is None:
            return (self.original,) if self.original is not None else ()
        return source.thread_identity.transcript_scope().original_threads()

    def __call__(self, sessions: SessionNavigator) -> SessionScope:
        source = self.factory()
        source.session_details = self.details
        source.thread_identity.bind_initial_identity(self.details)
        return source

    @property
    def address(self) -> str:
        return self.mode

    def source(self, sessions: SessionNavigator) -> SessionScope | None:
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
        sessions.app.coordination_access.confirm(selected)
        if sessions.get(self.mode) is not self:
            return
        source = self.source(sessions)
        if source is None:
            return
        original = next(
            (
                identity
                for root, identity in self.original_threads(sessions)
                if selected.serves(root)
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
        binding = thread.owner_binding(snapshot)
        plan = ExistingOwnerPlan.from_binding(binding)
        if not plan.available:
            return
        await source.operational_binding.reconnect_session(
            source, plan.require_plan()
        )

    def unobserved_tab(self) -> OpenTab:
        return NamedTab(self.identity, self.details.name.display or "New Session")

    def tab(self, sessions: SessionNavigator, observed: Observing) -> OpenTab:
        # The original wire identity exists before a native view. Unopened tabs
        # still show backend status/unread; attachment state belongs to a view.
        row = next(
            (
                row
                for root, identity in self.original_threads(sessions)
                if observed.observes(root)
                and (row := observed.sidebar.threads.rows.get(identity.name)) is not None
                and row.incarnation == identity
            ),
            None,
        )
        if row is not None:
            return ThreadTab(self.identity, self.thread_row(sessions, row))
        return self.unobserved_tab()

    async def return_to(self, sessions: SessionNavigator) -> None:
        app = sessions.app
        # Another session is preferred to a file or history tab between them.
        remaining = [
            details.identity
            for details in app.session_tracker.ordered_sessions
            if details.identity != self.identity
        ]
        await app.select_session(
            app.tab_order.previous(self.identity, eligible=remaining or None)
        )

    def forget(self, sessions: SessionNavigator) -> None:
        super().forget(sessions)
        sessions.app.session_tracker.close_session(self.identity)


class PreviewSessionEntry(SessionEntry):
    """A read-only file in its own tab."""

    def __init__(self, identity: TabIdentity, path: Path) -> None:
        super().__init__(identity)
        self.path = path

    @abstractmethod
    def content(self) -> object:
        """The frontend's view of the file's content."""

    @property
    def title(self) -> str:
        return self.path.name

    @property
    def address(self) -> Path:
        return self.path

    def unobserved_tab(self) -> OpenTab:
        return NamedTab(self.identity, self.title)


class AcpLogSessionEntry(PreviewSessionEntry):
    """An agent's ACP log in its own tab, named for the agent and start time in the file name."""

    @property
    def title(self) -> str:
        return f"ACP log · {self.path.stem}"
