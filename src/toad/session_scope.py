"""Logical session capabilities, independent of concrete widgets and screens."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Never

from agent_comms.channel_targets import ThreadTarget
from agent_comms.errors import RelationViolationError
from agent_comms.route_selection import RouteSelection
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.ui_model.observation import ReadTranscript, ReadTranscriptUpdate

from toad.app_node import ToadNode
from toad.core.events import ThreadRowsChanged
from toad.core_event_carrier import ThreadCallbackSubscription
from toad.navigation_context import NavigationOwner
from toad.project_path_owner import ProjectPathOwner
from toad.resource_release import ResourceRelease
from toad.status_thread import NoStatusThread, StatusThread

if TYPE_CHECKING:
    from textual.command import Provider
    from textual.dom import DOMNode

    from toad.agent_schema import AgentDefinition
    from toad.navigation_target import NavigationTarget
    from toad.session_presentation import OperationalSessionPresentation
    from toad.thread_identity import SessionIdentity


class TranscriptScope(ABC):
    """A transcript address owns its reads, observations and absent behavior."""

    @property
    @abstractmethod
    def readable(self) -> bool: ...

    @abstractmethod
    def original_threads(
        self, identity: SessionIdentity
    ) -> tuple[tuple[str, ThreadIncarnation], ...]: ...

    @abstractmethod
    def status_thread(self, access) -> StatusThread: ...

    @abstractmethod
    def observe(self, view, access, resume) -> ResourceRelease: ...

    @abstractmethod
    def snapshot_request(self, **bounds) -> ReadTranscript: ...

    @abstractmethod
    def update_request(self, previous, **bounds) -> ReadTranscriptUpdate: ...

    @abstractmethod
    def mailbox_target(self) -> ThreadTarget: ...

    @abstractmethod
    async def submit_mailbox(
        self, view, event, conversation_type, presented
    ) -> None: ...


@dataclass(frozen=True)
class KnownTranscript(TranscriptScope):
    root: str
    name: str
    readable = True

    def original_threads(
        self, identity: SessionIdentity
    ) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ((self.root, identity.thread_incarnation()),)

    def status_thread(self, access) -> StatusThread:
        return StatusThread.for_root(Path(self.root), self.name, access)

    def observe(self, view, access, resume) -> ResourceRelease:
        release = ResourceRelease()
        release.callback(
            view.retire_core,
            view.observe_core_callback(
                access.events,
                ThreadRowsChanged,
                resume,
                factory=partial(
                    ThreadCallbackSubscription, scope=(self.root, self.name)
                ),
            ),
        )
        return release

    def snapshot_request(self, **bounds) -> ReadTranscript:
        return ReadTranscript(self.root, self.name, **bounds)

    def update_request(self, previous, **bounds) -> ReadTranscriptUpdate:
        return ReadTranscriptUpdate(self.root, self.name, previous=previous, **bounds)

    def mailbox_target(self) -> ThreadTarget:
        return ThreadTarget(self.name)

    async def submit_mailbox(self, view, event, conversation_type, presented) -> None:
        await view.submit_comms_message(
            self.root,
            conversation_type(self.mailbox_target()),
            event.body,
            lambda: view.is_attached and view.transcript.binding.thread_scope == self,
            presented,
        )


@dataclass(frozen=True)
class NoTranscript(TranscriptScope):
    readable = False

    def original_threads(
        self, identity: SessionIdentity
    ) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ()

    def status_thread(self, access) -> StatusThread:
        return NoStatusThread()

    def observe(self, view, access, resume) -> ResourceRelease:
        return ResourceRelease()

    def unavailable(self) -> Never:
        raise ValueError("Transcript paging requires a bound thread")

    def snapshot_request(self, **bounds) -> Never:
        self.unavailable()

    def update_request(self, previous, **bounds) -> Never:
        self.unavailable()

    def mailbox_target(self) -> Never:
        self.unavailable()

    async def submit_mailbox(self, view, event, conversation_type, presented) -> None:
        view.delivery_refused("CLI transcript is not ready", event.body)


class SessionOrigin:
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


class SessionScope(NavigationOwner, ProjectPathOwner, ToadNode):
    """The session answers read by ancestors and workspace owners."""

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
    @abstractmethod
    def navigation_target(self) -> NavigationTarget: ...

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


class ProjectSessionOrigin(SessionOrigin, SessionScope):
    """A project source may navigate and resolve threads without an ACP session."""

    @property
    def origin(self) -> SessionOrigin:
        return self

    def transcript_scope(self) -> TranscriptScope:
        return self.thread_identity.transcript_scope()

    def require(self) -> ProjectSessionOrigin:
        return self

    def resolve_thread(self) -> str:
        identity = self.thread_identity
        selected = RouteSelection.capture(identity.wire_root())
        service = self.app.coordination_access.require(selected).service
        return identity.resolve_thread(service.registry, self.project_root)

    def agent_for_opening(
        self, default: AgentDefinition | None
    ) -> AgentDefinition | None:
        return default


class AgentBinding(ABC):
    """The native launch selection, decoded once from constructor arguments."""

    @classmethod
    def of(cls, agent: AgentDefinition | None, session_id: str | None) -> AgentBinding:
        if agent is None:
            return NoAgent()
        if session_id is None:
            return AgentAttached(agent)
        return AgentSession(agent, session_id)

    @abstractmethod
    def opening_agent(
        self, app_agent: AgentDefinition | None
    ) -> AgentDefinition | None: ...

    @abstractmethod
    def attached(self, app_agent: AgentDefinition | None) -> AgentBinding: ...

    @abstractmethod
    def matches_launch(
        self, origin: ViewSessionOrigin, agent_identity: str, session_id: str
    ) -> bool: ...

    @abstractmethod
    def agent_definition(self) -> AgentDefinition | None: ...

    def saved_session_id(self) -> str | None:
        return None


@dataclass(frozen=True)
class NoAgent(AgentBinding):
    def opening_agent(
        self, app_agent: AgentDefinition | None
    ) -> AgentDefinition | None:
        return app_agent

    def attached(self, app_agent: AgentDefinition | None) -> AgentBinding:
        return AgentBinding.of(app_agent, None)

    def matches_launch(
        self, origin: ViewSessionOrigin, agent_identity: str, session_id: str
    ) -> bool:
        return False

    def agent_definition(self) -> None:
        return None


@dataclass(frozen=True)
class AgentAttached(AgentBinding):
    agent: AgentDefinition

    def opening_agent(self, app_agent: AgentDefinition | None) -> AgentDefinition:
        return self.agent

    def attached(self, app_agent: AgentDefinition | None) -> AgentBinding:
        return self

    def agent_definition(self) -> AgentDefinition:
        return self.agent

    def matches_launch(
        self, origin: ViewSessionOrigin, agent_identity: str, session_id: str
    ) -> bool:
        return self.agent.identity == agent_identity and self.matches_session(
            origin, session_id
        )

    def matches_session(self, origin: ViewSessionOrigin, session_id: str) -> bool:
        if origin.presentation.operational_binding.matches_session(session_id):
            return True
        root = origin.coordination_root
        return (
            root is not None
            and origin.app.coordination_access.require(
                RouteSelection.capture(root)
            ).service.registry.canonical_name(session_id)
            == origin.resolve_thread()
        )


@dataclass(frozen=True)
class AgentSession(AgentAttached):
    session_id: str

    def saved_session_id(self) -> str:
        return self.session_id

    def matches_session(self, origin: ViewSessionOrigin, session_id: str) -> bool:
        return self.session_id == session_id or super().matches_session(
            origin, session_id
        )


class ViewSessionOrigin(ProjectSessionOrigin):
    """Only actual native-session views own agent/session launch matching."""

    _agent_binding: AgentBinding

    def agent_for_opening(
        self, default: AgentDefinition | None
    ) -> AgentDefinition | None:
        return self._agent_binding.opening_agent(default)

    def attach_agent_definition(self) -> AgentDefinition | None:
        self._agent_binding = self._agent_binding.attached(self.app.agent_data)
        return self._agent_binding.opening_agent(None)

    def use_mailbox(self) -> None:
        self._agent_binding = NoAgent()

    def matches_launch(self, agent_identity: str, session_id: str) -> bool:
        return self._agent_binding.matches_launch(self, agent_identity, session_id)
