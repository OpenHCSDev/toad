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
from textual.dom import DOMNode

from toad.core.events import ThreadRowsChanged
from toad.core_event_carrier import ThreadCallbackSubscription
from toad.navigation_context import NavigationOwner
from toad.project_path_owner import ProjectPathOwner
from toad.resource_release import ResourceRelease
from toad.status_thread import NoStatusThread, StatusThread

if TYPE_CHECKING:
    from textual.command import Provider

    from toad.agent_schema import AgentDefinition
    from toad.app import ToadApp
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


class ViewSessionOrigin(ProjectSessionOrigin):
    """Only actual native-session views own agent/session launch matching."""

    _agent: AgentDefinition | None
    _agent_session_id: str | None

    def agent_for_opening(
        self, default: AgentDefinition | None
    ) -> AgentDefinition | None:
        return self._agent or default

    def attach_agent_definition(self) -> AgentDefinition | None:
        self._agent = self._agent or self.app.agent_data
        return self._agent

    def use_mailbox(self) -> None:
        self._agent = None

    def matches_launch(self, agent_identity: str, session_id: str) -> bool:
        if self._agent is None or self._agent.identity != agent_identity:
            return False
        live = self.presentation.operational_binding
        if session_id == self._agent_session_id or live.matches_session(session_id):
            return True
        root = self.coordination_root
        return (
            root is not None
            and self.app.coordination_access.require(
                RouteSelection.capture(root)
            ).service.registry.canonical_name(session_id)
            == self.resolve_thread()
        )
