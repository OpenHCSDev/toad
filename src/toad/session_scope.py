"""The session capability consumed by descendants and workspace owners.

DOMNode owns native ancestry, queries and descriptors. SessionView supplies
session behavior; the capability imports neither a widget nor a screen.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.route_selection import RouteSelection
from textual.dom import DOMNode

from toad.project_path_owner import ProjectPathOwner

if TYPE_CHECKING:
    from textual.command import Provider

    from toad.agent_schema import AgentDefinition
    from toad.app import ToadApp
    from toad.navigation_target import NavigationContext
    from toad.session_presentation import OperationalSessionPresentation
    from toad.thread_identity import SessionIdentity


class SessionScope(ProjectPathOwner, DOMNode):
    """A logical session, without a dependency on its concrete widget."""

    # Concrete view state stays data: abstract properties would shadow inherited
    # setters or instance attributes. Native descriptors come from DOMNode.
    app: ToadApp
    COMMANDS: set[type[Provider]]
    AUTO_FOCUS: str
    shows_channels: bool
    footer_compact: bool
    presentation: OperationalSessionPresentation
    navigation_context: NavigationContext

    @property
    @abstractmethod
    def is_current(self) -> bool: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    @property
    @abstractmethod
    def navigation_target_name(self) -> str | None: ...

    @property
    @abstractmethod
    def origin(self) -> SessionOrigin | None: ...

    @property
    @abstractmethod
    def thread_identity(self) -> SessionIdentity: ...

    @abstractmethod
    def belongs_to_wire(self, root: str | Path) -> bool: ...

    @abstractmethod
    def sidebars(self) -> tuple[DOMNode, ...]: ...

    @abstractmethod
    def sidebar_focus_target(self) -> DOMNode | None: ...

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


class SessionOrigin(SessionScope):
    """An operational view that supplies the origin of sessions and histories."""

    _agent: AgentDefinition | None

    @property
    def origin(self) -> SessionOrigin:
        return self

    def transcript_scope(self) -> tuple[str, str] | None:
        return self.thread_identity.transcript_scope()

    def resolve_thread(self) -> str:
        identity = self.thread_identity
        selected = RouteSelection.capture(identity.wire_root())
        service = self.app.coordination_access.require(selected).service
        return identity.resolve_thread(service.registry, self.project_root)

    def has_agent(self) -> bool:
        return self._agent is not None
