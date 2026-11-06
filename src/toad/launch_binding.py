"""A launch's agent: whether it attached one, which, which session, and what that does to the
conversation and the view session it builds."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial

from agent_comms.repo import Checkout
from textual.abstract_hooks import AbstractHooksMeta

from toad.agent_binding import AgentConnection
from toad.agent_schema import AgentDefinition
from toad.app_node import ToadNode
from toad.thread_identity import SessionIdentity
from toad.transcript_scope import TranscriptScope


class AgentConversation(ToadNode):
    """What a launch's agent binding does to the conversation it builds: give it the agent's
    definition (or none), resume a named session, and start its session."""

    @abstractmethod
    def attach_agent_definition(self, definition: AgentDefinition) -> None: ...

    @abstractmethod
    def clear_agent_definition(self) -> None: ...

    @abstractmethod
    def resume_agent_session(self, session_id: str) -> None: ...

    @abstractmethod
    def start_native_session(self) -> None: ...


class AgentOrigin(ToadNode):
    """What a binding reads of the view session it attaches to: whether it is current, its
    transcript scope, and its live agent connection."""

    @property
    @abstractmethod
    def is_current(self) -> bool: ...

    @abstractmethod
    def transcript_scope(self) -> TranscriptScope: ...

    @property
    @abstractmethod
    def operational_binding(self) -> AgentConnection: ...


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
    def make_conversation[C: AgentConversation](self, constructor: partial[C]) -> C: ...

    @abstractmethod
    def attach_to(
        self, origin: AgentOrigin, conversation: AgentConversation
    ) -> None: ...

    @abstractmethod
    def matches_launch(
        self, origin: AgentOrigin, agent_identity: str, session_id: str
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

    def make_conversation[C: AgentConversation](self, constructor: partial[C]) -> C:
        return constructor()

    def attach_to(self, origin: AgentOrigin, conversation: AgentConversation) -> None:
        conversation.clear_agent_definition()

    def matches_launch(
        self, origin: AgentOrigin, agent_identity: str, session_id: str
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

    def make_conversation[C: AgentConversation](self, constructor: partial[C]) -> C:
        return constructor(agent=self.agent)

    def attach_to(self, origin: AgentOrigin, conversation: AgentConversation) -> None:
        conversation.attach_agent_definition(self.agent)
        if origin.is_current:
            conversation.start_native_session()

    def matches_launch(
        self, origin: AgentOrigin, agent_identity: str, session_id: str
    ) -> bool:
        return self.agent.identity == agent_identity and self.matches_session(
            origin, session_id
        )

    async def start_session(self, app: StartsSessions, project: Checkout) -> None:
        await app.start_agent_session(self, project)

    def matches_session(self, origin: AgentOrigin, session_id: str) -> bool:
        return origin.operational_binding.matches_session(
            session_id
        ) or origin.transcript_scope().matches_session(
            origin.app.coordination_access, session_id
        )


@dataclass(frozen=True)
class AgentSession(AgentAttached):
    session_id: str

    def attach_to(self, origin: AgentOrigin, conversation: AgentConversation) -> None:
        conversation.resume_agent_session(self.session_id)
        super().attach_to(origin, conversation)

    async def start_session(self, app: StartsSessions, project: Checkout) -> None:
        """A new session, not this one again."""
        await AgentAttached(self.agent).start_session(app, project)

    def make_conversation[C: AgentConversation](self, constructor: partial[C]) -> C:
        return super().make_conversation(
            partial(constructor, agent_session_id=self.session_id)
        )

    def initial_identity(self, empty: SessionIdentity) -> SessionIdentity:
        return empty.with_session(self.session_id)

    def matches_session(self, origin: AgentOrigin, session_id: str) -> bool:
        return self.session_id == session_id or super().matches_session(
            origin, session_id
        )
