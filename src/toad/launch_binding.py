"""A launch's agent: whether it attached one, which, which session, and what that does to the
conversation and the view session it builds."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from collections.abc import Callable
from functools import partial
from time import time_ns

from agent_comms.projects.checkouts import Checkout
from metaclass_registry import AbstractHooksMeta

from toad.agent_binding import AgentConnection
from toad.client.agent_processes import AgentProcesses
from toad.client.agent_schema import AgentDefinition
from toad.client.agents import read_agents
from toad.client.db import DB
from toad.core import session_requests
from toad.core.events import CoreEventStream
from toad.surface_binding import SurfaceBinding
from toad.thread_identity import SessionIdentity
from toad.transcript_scope import TranscriptScope
from agent_comms.nominal.field_codec import AcpSessionId, NoAcpSessionId


class AgentConversation(metaclass=AbstractHooksMeta):
    """What a launch's agent binding does to the conversation it builds: hand it the launch,
    resume a named session, and start its session. Every frontend's agent conversation
    inherits the chain (launch → unbound start → its sources create the agent); each answers
    only how it defers the start, shows a view without an agent, and receives the agent's
    events (`agent_surface`)."""

    launch: AgentBinding
    _agent_session_id: AcpSessionId | NoAcpSessionId

    def attach_launch(self, launch: AgentBinding) -> None:
        """Selection changes write the conversation's launch at its owner."""
        self.launch = launch

    def resume_agent_session(self, session_id: AcpSessionId) -> None:
        self._agent_session_id = session_id

    def start_native_session(self) -> None:
        self.agent_binding.start_session(self)

    def start_unbound_session(self) -> None:
        self.launch.start_unbound(self)

    def _start_agent(self) -> None:
        self.operational_sources.start_agent(self)

    def present_without_agent(self) -> None:
        """No agent to start: show the shell's info and take input."""
        self.show_agent_info(self.operational_sources.agent_info(self))
        self.session_ready()

    @abstractmethod
    def defer_agent_start(self) -> None:
        """Start the attached agent once the frame is presented."""

    @abstractmethod
    def agent_surface(self, events: CoreEventStream) -> SurfaceBinding:
        """How this view receives its bound agent's events and presents its tools,
        permissions and terminals."""

    def before_turn_settle(self) -> None:
        """Frontend cleanup before settling live output at the end of a turn."""

    async def before_turn_boundary(self) -> None:
        """Frontend cleanup after output settles and before the turn boundary."""

    def after_turn_boundary(self) -> None:
        """Frontend bookkeeping once the turn boundary is recorded."""

    @abstractmethod
    async def present_stop_note(self, text: str) -> None:
        """Present a turn stop-reason note to the reader."""

    @abstractmethod
    async def present_submission_error(self, detail: str) -> None:
        """Present an internal submission failure note to the reader."""

    async def agent_turn_over(self, stop_reason) -> None:
        """The turn ended: record usage, settle output, show any stop note and notify."""
        self.turns.finish_client()
        self.before_turn_settle()
        model = self.agent_binding.configuration.model.selected
        if model is not None:
            stop_reason.record_usage(
                partial(
                    self.run_worker,
                    partial(
                        DB().record_model_usage,
                        self.model_history_scope,
                        model.value,
                        last_used=time_ns(),
                    ),
                )
            )
        await self.output.settle()
        await self.before_turn_boundary()
        self.output.boundary()
        self.after_turn_boundary()
        if stop_reason.note:
            await self.present_stop_note(
                stop_reason.note.replace("$AGENT", (self.agent_title or "agent").title())
            )
        if self.app.settings.notifications.turn_over:
            self.app.input_attention.notify(
                f"{self.agent_title} has finished working",
                title="Waiting for input",
                sound="turn-over",
            )

    async def submission_request_failed(self, error, text: str) -> None:
        """The prompt never reached the agent: restore the draft and show the error."""
        self.turns.finish_client()
        self.restore_composer_draft(text)
        await self.present_submission_error(str(error) or "no details were provided")


class AgentOrigin(metaclass=AbstractHooksMeta):
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


class LaunchAgentRefused(LookupError):
    """The launch's ``--agent`` names no agent this launch can attach."""


class UnknownAgent(LaunchAgentRefused):
    """No configured agent answers to the requested name."""

    def __init__(self, requested: str, known: tuple[str, ...]) -> None:
        super().__init__(f"Unknown agent {requested!r}. Known agents: {', '.join(known)}")
        self.requested = requested
        self.known = known


class AgentBinding(ABC):
    """Known native launch state carries construction and attachment behavior."""

    @staticmethod
    async def launched(requested: str, processes: AgentProcesses) -> AgentBinding:
        """The launch's agent for the name the user asked for (empty: none), attached when
        ``processes`` (the launch's Core connection) starts agents; Toad's and Qt's ``-a``."""
        if not requested:
            return NoAgent()
        wanted = requested.lower()
        agents = await read_agents()
        for agent in agents.values():
            if wanted in (agent.short_name.lower(), agent.identity.lower()):
                return processes.start(partial(AgentAttached, agent), AgentBinding.refused_launch)
        raise UnknownAgent(requested, tuple(sorted(
            f"{agent.short_name} ({agent.identity})" if agent.short_name else agent.identity
            for agent in agents.values())))

    @staticmethod
    def refused_launch(reason: str) -> AgentBinding:
        raise LaunchAgentRefused(reason)

    @property
    @abstractmethod
    def welcome_prefix(self) -> str: ...

    @abstractmethod
    def attached(self, app_binding: AgentBinding) -> AgentBinding: ...

    @abstractmethod
    def for_session(self, session_id: AcpSessionId) -> AgentBinding: ...

    def make_conversation[C: AgentConversation](self, constructor: partial[C]) -> C:
        return constructor(launch=self)

    def attach_to(self, origin: AgentOrigin, conversation: AgentConversation) -> None:
        conversation.attach_launch(self)

    def selected_agent[T](self, absent: T, attached: Callable[[AgentDefinition], T]) -> T:
        """The caller's answer for this launch: its no-agent answer, or one from the agent."""
        return absent

    def publish_usage(self, publish: Callable[..., object], event: str, **fields: object) -> None:
        """Usage is counted per agent; a launch without one reports nothing."""

    def start_unbound(self, conversation: AgentConversation) -> None:
        conversation.present_without_agent()

    def request_new_session(self, events: CoreEventStream, working_directory: str, prompt: str) -> None:
        """/new opens a session of the attached agent; without one there is nothing to open."""

    def require_agent(self) -> AgentDefinition:
        raise ValueError("This launch attached no agent to start.")

    @abstractmethod
    def matches_launch(
        self, origin: AgentOrigin, agent_identity: str, session_id: AcpSessionId
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

    def for_session(self, session_id: AcpSessionId) -> AgentBinding:
        return self

    def matches_launch(
        self, origin: AgentOrigin, agent_identity: str, session_id: AcpSessionId
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

    def for_session(self, session_id: AcpSessionId) -> AgentBinding:
        return AgentSession(self.agent, session_id)

    def attach_to(self, origin: AgentOrigin, conversation: AgentConversation) -> None:
        super().attach_to(origin, conversation)
        if origin.is_current:
            conversation.start_native_session()

    def selected_agent[T](self, absent: T, attached: Callable[[AgentDefinition], T]) -> T:
        return attached(self.agent)

    def publish_usage(self, publish: Callable[..., object], event: str, **fields: object) -> None:
        publish(event, agent=self.agent.identity, **fields)

    def start_unbound(self, conversation: AgentConversation) -> None:
        conversation.defer_agent_start()

    def request_new_session(self, events: CoreEventStream, working_directory: str, prompt: str) -> None:
        events.publish(session_requests.SessionNew(working_directory, self.agent.identity, prompt))

    def require_agent(self) -> AgentDefinition:
        return self.agent

    def matches_launch(
        self, origin: AgentOrigin, agent_identity: str, session_id: AcpSessionId
    ) -> bool:
        return self.agent.identity == agent_identity and self.matches_session(
            origin, session_id
        )

    async def start_session(self, app: StartsSessions, project: Checkout) -> None:
        await app.start_agent_session(self, project)

    def matches_session(self, origin: AgentOrigin, session_id: AcpSessionId) -> bool:
        return origin.operational_binding.matches_session(
            session_id
        ) or origin.transcript_scope().matches_session(
            origin.app.coordination_access, session_id
        )


@dataclass(frozen=True)
class AgentSession(AgentAttached):
    session_id: AcpSessionId

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

    def matches_session(self, origin: AgentOrigin, session_id: AcpSessionId) -> bool:
        return self.session_id == session_id or super().matches_session(
            origin, session_id
        )
