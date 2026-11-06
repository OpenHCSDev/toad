"""Logical session capabilities, independent of concrete widgets and screens."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Never

from agent_comms.channel_targets import ThreadTarget
from agent_comms.repo import Checkout
from agent_comms.coordination.errors import CoordinationReadUnavailable, ReadAgain
from agent_comms.errors import RelationViolationError, RouteChangedError
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.transport.tools.reads import TranscriptPageRead
from agent_comms.transcripts import AtFrontier, LatestPage, LivePageSource, PageLimit, PagePosition, PageSource
from agent_comms.ui_model.observation import (
    ReadTranscript,
    ReadTranscriptUpdate,
    TranscriptPublicationState,
)

from toad.app_node import ToadNode
from toad.core.events import ThreadRowsChanged
from toad.core_event_carrier import ThreadCallbackSubscription
from toad.input_decision import InputAccepted, InputDecision, TranscriptNotReady
from toad.navigation_context import NavigationScope
from toad.transcript_scope import NoTranscript, TranscriptScope
from toad.owner_preparation import ExistingOwnerPlan
from textual.abstract_hooks import AbstractHooksMeta
from toad.project_path_owner import CheckoutRoot, ProjectPathOwner
from toad.resource_release import ResourceRelease
from toad.status_thread import NoStatusThread, StatusThread
from agent_comms.message_reference import MessageReference

from toad.bus_submission import (
    BusDestination,
    SubmissionOwner,
    SubmissionStart,
    SubmittedText,
)

from toad.widget_actions import DeclaredWidgetActions
from agent_comms.thread_presentation import ThreadPresentation
from textual.command import Provider
from toad.widgets.side_bar import SideBar
from toad.agent_schema import AgentDefinition
from toad.comms_root import CoordinationAccess, Observing

from toad.conversation_kind import DmConversation
from toad.navigation_target import NavigationTarget

from toad.thread_identity import SessionIdentity

if TYPE_CHECKING:
    from toad.session_presentation import OperationalSessionPresentation
    from toad.widgets.conversation import Conversation


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
    """The session answers read by ancestors and workspace owners."""

    COMMANDS: ClassVar[set[type[Provider]]] = set()
    AUTO_FOCUS = ""
    footer_compact = False
    presentation: OperationalSessionPresentation

    async def _pre_process(self) -> bool:
        """Textual tears a failed start down; the workspace must not keep the dead tree."""
        started = await super()._pre_process()
        if not started:
            self.app.workspace_sessions.detach(self.id)
        return started

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

    def agent_for_opening(self, default: AgentBinding) -> AgentBinding:
        return default


class StartsSessions(metaclass=AbstractHooksMeta):
    """What a launch's New Session needs from the application it starts in."""

    @abstractmethod
    def open_thread_form(self, project: Checkout) -> None:
        """The native thread form, for a launch with no attached agent."""

    @abstractmethod
    async def start_agent_session(self, binding: AgentAttached, project: Checkout) -> None:
        """A new session of the agent this launch attached: saved, then opened."""


class AgentBinding(ABC):
    """Known native launch state carries construction and attachment behavior."""

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

    @abstractmethod
    async def start_session(self, app: StartsSessions, project: Checkout) -> None:
        """New Session in this launch: a native thread form, or the attached agent's session."""


@dataclass(frozen=True)
class NoAgent(AgentBinding):
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

    async def start_session(self, app: StartsSessions, project: Checkout) -> None:
        app.open_thread_form(project)


@dataclass(frozen=True)
class AgentAttached(AgentBinding):
    agent: AgentDefinition
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

    async def start_session(self, app: StartsSessions, project: Checkout) -> None:
        await app.start_agent_session(self, project)

    def matches_session(self, origin: ViewSessionOrigin, session_id: str) -> bool:
        return origin.presentation.operational_binding.matches_session(
            session_id
        ) or origin.transcript_scope().matches_session(
            origin.app.coordination_access, session_id
        )


@dataclass(frozen=True)
class AgentSession(AgentAttached):
    session_id: str

    def attach_to(self, origin: ViewSessionOrigin, conversation: Conversation) -> None:
        conversation._agent_session_id = self.session_id
        super().attach_to(origin, conversation)

    async def start_session(self, app: StartsSessions, project: Checkout) -> None:
        """A new session, not this one again."""
        await AgentAttached(self.agent).start_session(app, project)

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
        self._agent_binding = self._agent_binding.attached(
            self.app.agent_binding
        ).for_session(self.thread_identity.thread_name())
        return self._agent_binding

    def use_mailbox(self) -> None:
        self._agent_binding = NoAgent()

    def matches_launch(self, agent_identity: str, session_id: str) -> bool:
        return self._agent_binding.matches_launch(self, agent_identity, session_id)
