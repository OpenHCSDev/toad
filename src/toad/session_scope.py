"""Logical session capabilities, independent of concrete widgets and screens."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable
from pathlib import Path
from typing import ClassVar, Never

from agent_comms.nominal.field_codec import AcpSessionId, FieldCodec
from agent_comms.errors import RelationViolationError

from toad.app_node import ToadNode
from toad.navigation_context import NavigationOwner, NavigationScope, NoNavigationOwner
from toad.transcript_scope import NoTranscript, TranscriptScope
from textual.abstract_hooks import AbstractHooksMeta
from toad.project_path_owner import CheckoutRoot, ProjectPathOwner
from toad.widget_actions import DeclaredWidgetActions
from textual.command import Provider
from toad.widgets.side_bar import SideBar

from toad.navigation_target import NavigationTarget

from toad.launch_binding import AgentBinding, AgentOrigin, NoAgent
from toad.thread_identity import SessionIdentity

class SessionOrigin(metaclass=AbstractHooksMeta):
    """An origin answers for itself, including when its view is unavailable."""

    @abstractmethod
    def transcript_scope(self) -> TranscriptScope: ...

    @abstractmethod
    def resolve_thread(self) -> str: ...

    @abstractmethod
    def require(self) -> ProjectSessionOrigin: ...


class NoSessionOrigin(SessionOrigin):
    def __init__(self, view: str = "unavailable view") -> None:
        self.view = view

    def transcript_scope(self) -> NoTranscript:
        return NoTranscript()

    def require(self) -> Never:
        raise RelationViolationError(f"View {self.view!r} has no session origin")

    def resolve_thread(self) -> Never:
        self.require()


class SessionScope(ProjectPathOwner, NavigationScope, ToadNode):
    """The session answers read by ancestors and workspace owners.

    A compositing layer: the compositor retains this subtree's geometry while
    the tab is hidden, so showing it again skips the full layout walk.
    """

    COMPOSITING_LAYER = True
    COMMANDS: ClassVar[set[type[Provider]]] = set()
    AUTO_FOCUS = ""
    footer_compact = False

    @property
    def navigation_owner(self) -> NavigationOwner:
        """A session that does not navigate answers the owner that refuses."""
        return NoNavigationOwner(self.app)

    async def _pre_process(self) -> bool:
        """Textual tears a failed start down; the workspace must not keep the dead tree."""
        started = await super()._pre_process()
        if not started:
            self.app.workspace_sessions.detach(self.id)
        return started

    def matches_launch(self, agent_identity: str, session_id: AcpSessionId) -> bool:
        return False

    @property
    @abstractmethod
    def is_current(self) -> bool: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    @property
    @abstractmethod
    def navigation_target(self) -> NavigationTarget: ...

    @property
    @abstractmethod
    def origin(self) -> SessionOrigin: ...

    @property
    @abstractmethod
    def thread_identity(self) -> SessionIdentity: ...

    @abstractmethod
    def belongs_to_wire(self, root: Path) -> bool: ...

    @abstractmethod
    def sidebars(self) -> tuple[SideBar, ...]: ...

    @abstractmethod
    def keyboard_scopes(self) -> tuple[DeclaredWidgetActions, ...]: ...

    def focus_sidebar_return(self) -> None:
        """A view without a sidebar return target has nothing to focus."""

    @abstractmethod
    async def prepare_presentation(self) -> None: ...

    @abstractmethod
    async def retire_presentation(self) -> None: ...

    @abstractmethod
    async def close_presentation(self) -> None: ...

    @abstractmethod
    def activate_session(self) -> None: ...

    @abstractmethod
    def close_core_events(self) -> None: ...

    @abstractmethod
    def remove(self) -> Awaitable[None]: ...


class ProjectSessionOrigin(SessionOrigin, CheckoutRoot, SessionScope):
    """A project source may navigate and resolve threads without an ACP session."""

    async def prepare_history_origin(self) -> None:
        """An agent view already has its thread; resident views acquire theirs."""

    @property
    def origin(self) -> SessionOrigin:
        return self

    def transcript_scope(self) -> TranscriptScope:
        return self.thread_identity.transcript_scope()

    def require(self) -> ProjectSessionOrigin:
        return self

    def resolve_thread(self) -> str:
        identity = self.thread_identity
        observed = self.app.coordination_access.observing(identity.wire_root())
        return identity.resolve_thread(observed, self.project_root)

    _agent_binding: AgentBinding = NoAgent()
    """A project origin with no launch of its own opens views with the app's binding."""

    def agent_for_opening(self, default: AgentBinding) -> AgentBinding:
        return self._agent_binding.attached(default)


class ViewSessionOrigin(ProjectSessionOrigin, AgentOrigin):
    """Only actual native-session views own agent/session launch matching."""

    def attach_agent_definition(self) -> AgentBinding:
        self._agent_binding = self._agent_binding.attached(
            self.app.agent_binding
        ).for_session(FieldCodec.decode(AcpSessionId, self.thread_identity.thread_name()))
        return self._agent_binding

    def use_mailbox(self) -> None:
        self._agent_binding = NoAgent()

    def matches_launch(self, agent_identity: str, session_id: AcpSessionId) -> bool:
        return self._agent_binding.matches_launch(self, agent_identity, session_id)
