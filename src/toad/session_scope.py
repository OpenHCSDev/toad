"""The session contract consumed by descendants and workspace owners.

Like ProjectPathOwner, this abstract capability has no ABC metaclass: Textual
owns its widgets' metaclass. Native widget methods and data descriptors remain
implemented by the view's existing parents, not by a forwarding wrapper.
"""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.route_selection import RouteSelection
from toad.project_path_owner import ProjectPathOwner

if TYPE_CHECKING:
    from textual.command import Provider
    from textual.dom import DOMNode
    from toad.agent_schema import AgentDefinition
    from toad.navigation_target import NavigationContext
    from toad.session_presentation import OperationalSessionPresentation
    from toad.thread_identity import SessionIdentity


class SessionOrigin:
    """The existing agent/project origin of sessions and histories."""

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
        return identity.resolve_thread(service.registry, self.project_path)

    def has_agent(self) -> bool:
        return self._agent is not None


class SessionScope(ProjectPathOwner):
    """What a mounted logical session answers, independently of its screen."""

    # Existing native data descriptors and concrete-view state. An abstract
    # property here would shadow their inherited setters or instance attributes.
    id: str | None
    display: bool
    screen: DOMNode
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
    def query_one_optional[Node](
        self, selector: str | type[Node], expect_type: type[Node] | None = None,
    ) -> Node | None: ...

    @abstractmethod
    def remove(self) -> Awaitable[None]: ...
