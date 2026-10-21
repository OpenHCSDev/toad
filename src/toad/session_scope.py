"""Logical session capabilities, independent of concrete widgets and screens."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Never

from agent_comms.errors import RelationViolationError
from agent_comms.route_selection import RouteSelection
from textual.dom import DOMNode

from toad.navigation_context import NavigationOwner
from toad.project_path_owner import ProjectPathOwner

if TYPE_CHECKING:
    from textual.command import Provider

    from toad.agent_schema import AgentDefinition
    from toad.app import ToadApp
    from toad.session_presentation import OperationalSessionPresentation
    from toad.thread_identity import SessionIdentity


class SessionOrigin:
    """An origin answers for itself, including when its view is unavailable."""

    @abstractmethod
    def transcript_scope(self) -> tuple[str, str] | None: ...

    @abstractmethod
    def has_agent(self) -> bool: ...

    @abstractmethod
    def resolve_thread(self) -> str: ...

    @abstractmethod
    def require(self) -> ViewSessionOrigin: ...


class NoSessionOrigin(SessionOrigin):
    def __init__(self, view: str = "unavailable view") -> None:
        self.view = view

    def transcript_scope(self) -> None:
        return None

    def has_agent(self) -> bool:
        return False

    def require(self) -> Never:
        raise RelationViolationError(f"View {self.view!r} has no session origin")

    def resolve_thread(self) -> Never:
        self.require()


class SessionScope(NavigationOwner, ProjectPathOwner, DOMNode):
    """The session answers read by ancestors and workspace owners."""

    app: ToadApp
    COMMANDS: ClassVar[set[type[Provider]]] = set()
    AUTO_FOCUS = ""
    shows_channels = True
    footer_compact = False
    presentation: OperationalSessionPresentation

    @property
    @abstractmethod
    def is_current(self) -> bool: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    @property
    def navigation_target_name(self) -> str | None:
        """Views without a displayed destination have no navigation name."""
        return None

    @property
    @abstractmethod
    def origin(self) -> SessionOrigin: ...

    @property
    @abstractmethod
    def thread_identity(self) -> SessionIdentity: ...

    @abstractmethod
    def belongs_to_wire(self, root: str | Path) -> bool: ...

    @abstractmethod
    def sidebars(self) -> tuple[DOMNode, ...]: ...

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


class ViewSessionOrigin(SessionOrigin, SessionScope):
    """The existing operational agent/project origin shared by real views."""

    _agent: AgentDefinition | None

    @property
    def origin(self) -> SessionOrigin:
        return self

    def transcript_scope(self) -> tuple[str, str] | None:
        return self.thread_identity.transcript_scope()

    def require(self) -> ViewSessionOrigin:
        return self

    def resolve_thread(self) -> str:
        identity = self.thread_identity
        selected = RouteSelection.capture(identity.wire_root())
        service = self.app.coordination_access.require(selected).service
        return identity.resolve_thread(service.registry, self.project_root)

    def has_agent(self) -> bool:
        return self._agent is not None
