"""Logical session capabilities, independent of concrete widgets and screens."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable
from pathlib import Path
from typing import ClassVar

from agent_comms.nominal.field_codec import AcpSessionId, FieldCodec

from textual.command import Provider
from textual.dom import DOMNode

from toad.app_node import ToadNode
from toad.client.session_scope import ProjectSessionOrigin, SessionOrigin
from toad.client.session_scope import SessionScope as SharedSessionScope
from toad.launch_binding import AgentBinding, AgentOrigin, NoAgent
from toad.navigation_context import NavigationOwner, NavigationScope, NoNavigationOwner
from toad.navigation_target import NavigationTarget
from toad.project_path_owner import ProjectPathOwner
from toad.thread_identity import SessionIdentity
from toad.widget_actions import DeclaredWidgetActions
from toad.widgets.side_bar import SideBar


class ThreadIdentityScope(DOMNode):
    """The thread described by a panel, independent of the composer sending identity."""

    @property
    @abstractmethod
    def sidebar_thread_identity(self) -> SessionIdentity: ...


class SessionScope(SharedSessionScope, ThreadIdentityScope, ProjectPathOwner, NavigationScope, ToadNode):
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

    @property
    def sidebar_thread_identity(self) -> SessionIdentity:
        return self.thread_identity

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


class ViewSessionOrigin(ProjectSessionOrigin, SessionScope, AgentOrigin):
    """Only actual native-session views own agent/session launch matching."""

    _agent_binding: AgentBinding = NoAgent()

    def agent_for_opening(self, default: AgentBinding) -> AgentBinding:
        return self._agent_binding.attached(default)

    def attach_agent_definition(self) -> AgentBinding:
        self._agent_binding = self._agent_binding.attached(
            self.app.agent_binding
        ).for_session(FieldCodec.decode(AcpSessionId, self.thread_identity.thread_name()))
        return self._agent_binding

    def use_mailbox(self) -> None:
        self._agent_binding = NoAgent()

    def matches_launch(self, agent_identity: str, session_id: AcpSessionId) -> bool:
        return self._agent_binding.matches_launch(self, agent_identity, session_id)
