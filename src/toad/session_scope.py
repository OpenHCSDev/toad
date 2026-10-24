"""Logical session capabilities, independent of concrete widgets and screens."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Never

from agent_comms.channel_targets import ThreadTarget
from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision
from agent_comms.errors import RelationViolationError
from agent_comms.route_selection import RouteSelection
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.ui_model.observation import (
    ReadTranscript,
    ReadTranscriptUpdate,
    TranscriptPublicationState,
)

from toad.app_node import ToadNode
from toad.constants import WELCOME
from toad.core.events import ThreadRowsChanged
from toad.core_event_carrier import ThreadCallbackSubscription
from toad.navigation_context import NavigationOwner
from toad.project_path_owner import ProjectPathOwner
from toad.resource_release import ResourceRelease
from toad.status_thread import NoStatusThread, StatusThread

if TYPE_CHECKING:
    from agent_comms.messages import Message
    from agent_comms.transcripts import TranscriptCursor
    from textual.command import Provider
    from textual.dom import DOMNode

    from toad.agent_schema import AgentDefinition
    from toad.comms_root import CoordinationAccess
    from toad.conversation_kind import DmConversation
    from toad.core.input_events import UserInputSubmitted
    from toad.navigation_target import NavigationTarget
    from toad.session_presentation import OperationalSessionPresentation
    from toad.thread_identity import SessionIdentity
    from toad.widgets.conversation import Conversation


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
    def matches_session(self, access: CoordinationAccess, session_id: str) -> bool: ...

    @abstractmethod
    def status_thread(self, access: CoordinationAccess) -> StatusThread: ...

    @abstractmethod
    def observe(
        self,
        view: Conversation,
        access: CoordinationAccess,
        resume: Callable[[ThreadRowsChanged], bool | None],
    ) -> ResourceRelease: ...

    @abstractmethod
    def snapshot_request(
        self,
        *,
        before: TranscriptCursor | None = None,
        after: TranscriptCursor | None = None,
        through: TranscriptCursor | None = None,
        historical_source: str | None = None,
    ) -> ReadTranscript: ...

    @abstractmethod
    def update_request(
        self,
        previous: TranscriptPublicationState,
        *,
        after: TranscriptCursor | None = None,
    ) -> ReadTranscriptUpdate: ...

    @abstractmethod
    def mailbox_target(self) -> ThreadTarget: ...

    @abstractmethod
    async def submit_mailbox(
        self,
        view: Conversation,
        event: UserInputSubmitted,
        conversation_type: type[DmConversation],
        presented: Callable[[Message | None], Awaitable[None]],
    ) -> None: ...

    @abstractmethod
    async def show_mailbox_status(
        self, view: Conversation, conversation_type: type[DmConversation]
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

    def matches_session(self, access: CoordinationAccess, session_id: str) -> bool:
        service = access.require(RouteSelection.capture(self.root)).service
        return (
            service.registry.canonical_name(session_id)
            == service.registry.require(self.name).name
        )

    def status_thread(self, access: CoordinationAccess) -> StatusThread:
        return StatusThread.for_root(Path(self.root), self.name, access)

    def observe(
        self,
        view: Conversation,
        access: CoordinationAccess,
        resume: Callable[[ThreadRowsChanged], bool | None],
    ) -> ResourceRelease:
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

    def snapshot_request(
        self,
        *,
        before: TranscriptCursor | None = None,
        after: TranscriptCursor | None = None,
        through: TranscriptCursor | None = None,
        historical_source: str | None = None,
    ) -> ReadTranscript:
        return ReadTranscript(
            self.root,
            self.name,
            before=before,
            after=after,
            through=through,
            historical_source=historical_source,
        )

    def update_request(
        self,
        previous: TranscriptPublicationState,
        *,
        after: TranscriptCursor | None = None,
    ) -> ReadTranscriptUpdate:
        return ReadTranscriptUpdate(self.root, self.name, previous=previous, after=after)

    def mailbox_target(self) -> ThreadTarget:
        return ThreadTarget(self.name)

    async def submit_mailbox(
        self,
        view: Conversation,
        event: UserInputSubmitted,
        conversation_type: type[DmConversation],
        presented: Callable[[Message | None], Awaitable[None]],
    ) -> None:
        await view.submit_comms_message(
            self.root,
            self.mailbox_conversation(view, conversation_type),
            event.body,
            lambda: self.shown_by(view),
            presented,
        )

    async def show_mailbox_status(
        self, view: Conversation, conversation_type: type[DmConversation]
    ) -> None:
        """A CLI thread shows the same Core configuration answer a DM shows."""
        try:
            comms = await view.app.coordination_access.transcripts.service(self.root)
            status = await self.mailbox_conversation(view, conversation_type).status_text(
                comms, read_only=False
            )
        except (CoordinationReadUnavailable, StaleRevision):
            # The next observed presentation reads the answer again.
            return
        if self.shown_by(view):
            view.thread_status = status

    def shown_by(self, view: Conversation) -> bool:
        """This transcript is still the one the view is bound to."""
        return view.is_attached and view.transcript.binding.thread_scope == self

    @staticmethod
    def mailbox_conversation(
        view: Conversation, conversation_type: type[DmConversation]
    ) -> DmConversation:
        return conversation_type(
            view.query_ancestor(SessionScope).thread_identity.thread_incarnation()
        )


@dataclass(frozen=True)
class NoTranscript(TranscriptScope):
    readable = False

    def original_threads(
        self, identity: SessionIdentity
    ) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ()

    def matches_session(self, access: CoordinationAccess, session_id: str) -> bool:
        return False

    def status_thread(self, access: CoordinationAccess) -> StatusThread:
        return NoStatusThread()

    def observe(
        self,
        view: Conversation,
        access: CoordinationAccess,
        resume: Callable[[ThreadRowsChanged], bool | None],
    ) -> ResourceRelease:
        return ResourceRelease()

    def unavailable(self) -> Never:
        raise ValueError("Transcript paging requires a bound thread")

    def snapshot_request(
        self,
        *,
        before: TranscriptCursor | None = None,
        after: TranscriptCursor | None = None,
        through: TranscriptCursor | None = None,
        historical_source: str | None = None,
    ) -> Never:
        self.unavailable()

    def update_request(
        self,
        previous: TranscriptPublicationState,
        *,
        after: TranscriptCursor | None = None,
    ) -> Never:
        self.unavailable()

    def mailbox_target(self) -> Never:
        self.unavailable()

    async def submit_mailbox(
        self,
        view: Conversation,
        event: UserInputSubmitted,
        conversation_type: type[DmConversation],
        presented: Callable[[Message | None], Awaitable[None]],
    ) -> None:
        view.delivery_refused("CLI transcript is not ready", event.body)

    async def show_mailbox_status(
        self, view: Conversation, conversation_type: type[DmConversation]
    ) -> None:
        """No bound thread has no configuration to show."""


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

    def matches_launch(self, agent_identity: str, session_id: str) -> bool:
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

    @abstractmethod
    def history_origin(self):
        """The durable opening source of this view's history tabs."""

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
        selected = RouteSelection.capture(identity.wire_root())
        service = self.app.coordination_access.require(selected).service
        return identity.resolve_thread(service.registry, self.project_root)

    def agent_for_opening(self, default: AgentBinding) -> AgentBinding:
        return default


class AgentBinding(ABC):
    """Known native launch state carries construction and attachment behavior."""

    startup_mode: ClassVar[str]

    @property
    @abstractmethod
    def welcome_prefix(self) -> str: ...

    @abstractmethod
    def attached(self, app_binding: AgentBinding) -> AgentBinding: ...

    @abstractmethod
    def for_session(self, session_id: str) -> AgentBinding: ...

    @abstractmethod
    def make_conversation(self, constructor: partial[Conversation]) -> Conversation: ...

    @abstractmethod
    def attach_to(
        self, origin: ViewSessionOrigin, conversation: Conversation
    ) -> None: ...

    @abstractmethod
    def matches_launch(
        self, origin: ViewSessionOrigin, agent_identity: str, session_id: str
    ) -> bool: ...

    def initial_identity(self, empty: SessionIdentity) -> SessionIdentity:
        return empty


@dataclass(frozen=True)
class NoAgent(AgentBinding):
    startup_mode = "store"

    @property
    def welcome_prefix(self) -> str:
        return ""

    def attached(self, app_binding: AgentBinding) -> AgentBinding:
        return app_binding

    def for_session(self, session_id: str) -> AgentBinding:
        return self

    def make_conversation(self, constructor: partial[Conversation]) -> Conversation:
        return constructor()

    def attach_to(self, origin: ViewSessionOrigin, conversation: Conversation) -> None:
        conversation.clear_agent_definition()

    def matches_launch(
        self, origin: ViewSessionOrigin, agent_identity: str, session_id: str
    ) -> bool:
        return False


@dataclass(frozen=True)
class AgentAttached(AgentBinding):
    agent: AgentDefinition
    startup_mode = WELCOME

    @property
    def welcome_prefix(self) -> str:
        return f"{self.agent.name} · "

    def attached(self, app_binding: AgentBinding) -> AgentBinding:
        return self

    def for_session(self, session_id: str) -> AgentBinding:
        return AgentSession(self.agent, session_id)

    def make_conversation(self, constructor: partial[Conversation]) -> Conversation:
        return constructor(agent=self.agent)

    def attach_to(self, origin: ViewSessionOrigin, conversation: Conversation) -> None:
        conversation.attach_agent_definition(self.agent)
        if origin.is_current:
            conversation.start_native_session()

    def matches_launch(
        self, origin: ViewSessionOrigin, agent_identity: str, session_id: str
    ) -> bool:
        return self.agent.identity == agent_identity and self.matches_session(
            origin, session_id
        )

    def matches_session(self, origin: ViewSessionOrigin, session_id: str) -> bool:
        return origin.presentation.operational_binding.matches_session(
            session_id
        ) or origin.transcript_scope().matches_session(
            origin.app.coordination_access, session_id
        )


@dataclass(frozen=True)
class AgentSession(AgentAttached):
    session_id: str

    def make_conversation(self, constructor: partial[Conversation]) -> Conversation:
        return super().make_conversation(
            partial(constructor, agent_session_id=self.session_id)
        )

    def initial_identity(self, empty: SessionIdentity) -> SessionIdentity:
        return empty.with_session(self.session_id)

    def matches_session(self, origin: ViewSessionOrigin, session_id: str) -> bool:
        return self.session_id == session_id or super().matches_session(
            origin, session_id
        )


class ViewSessionOrigin(ProjectSessionOrigin):
    """Only actual native-session views own agent/session launch matching."""

    _agent_binding: AgentBinding

    def agent_for_opening(self, default: AgentBinding) -> AgentBinding:
        return self._agent_binding.attached(default)

    def attach_agent_definition(self) -> AgentBinding:
        self._agent_binding = self._agent_binding.attached(self.app.agent_binding)
        return self._agent_binding

    def use_mailbox(self) -> None:
        self._agent_binding = NoAgent()

    def matches_launch(self, agent_identity: str, session_id: str) -> bool:
        return self._agent_binding.matches_launch(self, agent_identity, session_id)
