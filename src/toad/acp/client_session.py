"""One captured session authority for ACP client-side effects."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from acp.schema import PromptResponse
from agent_comms.acp_failure import ACPFailure, RequestFailure
from agent_comms.errors import RouteChangedError
from agent_comms.input_attempt import NotSentInput
from toad.core.events import LogAgentFail
from .queue_attachment import QueueActionRefused
from .status import ConfirmedPromptResult, PromptResult, StopReason

if TYPE_CHECKING:
    from .agent import Agent
    from .agent_session import SessionDisposition
    from .agent_controller import SessionBinding
from acp.exceptions import RequestError


@dataclass(frozen=True)
class ClientSessionRequest:
    agent: "Agent"
    session_id: str | None
    disposition: "SessionDisposition" = field(init=False)
    binding: "SessionBinding" = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'disposition', self.agent.session.disposition)
        object.__setattr__(self, 'binding', self.agent.controller.session)

    @property
    def current(self):
        return (self.agent.controller.session is self.binding
                and self.agent.session.disposition is self.disposition
                and self.agent.session.accepts_session(self.session_id))

    @property
    def retired(self):
        return not self.current

    def require(self):
        if not self.current:
            raise RequestError.invalid_params({'details': 'ACP client request belongs to a retired session'})

    async def prompt(self, content, metadata, require) -> PromptResult:
        """Decode once at the captured request's real SDK/write boundary."""
        process = self.agent.process
        try:
            await process.prepare_prompt(self.agent, require)
        except RequestError as error:
            failure = RequestFailure.from_error(error)
            return ResolvedFailurePromptResult(self, replace(failure, failure=replace(
                failure.failure, input_state=NotSentInput)))
        except (OSError, QueueActionRefused, RouteChangedError) as error:
            return ResolvedFailurePromptResult(self, RequestFailure(replace(ACPFailure.from_detail(
                None, f"{type(error).__name__}: {error}"), input_state=NotSentInput), False))
        try:
            response = await process.rpc.prompt(self.session_id, content, **metadata)
        except RequestError as error:
            return self.failed(RequestFailure.from_error(error))
        except OSError as error:
            return self.unconfirmed(RequestFailure(ACPFailure.from_detail(
                None, f"{type(error).__name__}: {error}"), False))
        return self.completed(response)

    def completed(self, response: PromptResponse) -> PromptResult:
        if self.retired:
            return self.unconfirmed(RequestFailure(ACPFailure.from_detail(
                None, "the captured ACP session retired before its reply"), False))
        return StopReason.from_acp(response)

    def failed(self, failure: RequestFailure) -> PromptResult:
        if self.retired:
            return self.unconfirmed(failure)
        return failure.failure.input_failure_result(
            lambda: ResolvedFailurePromptResult(self, failure),
            lambda: FailedPromptResult(self, failure),
        )

    def unconfirmed(self, failure: RequestFailure) -> UnconfirmedPromptResult:
        return UnconfirmedPromptResult(self, failure)

    def resolve(self, outcome: PromptResult) -> PromptResult:
        """Ordinary callers retain the answer, including unconfirmed input."""
        return outcome


@dataclass(frozen=True)
class UnfinishedPromptResult(PromptResult):
    request: ClientSessionRequest
    failure: RequestFailure

    def publish_failure(self) -> None:
        if self.request.current and not self.failure.notification_published:
            agent, failure = self.request.agent, self.failure.failure
            self.report_failure(agent, LogAgentFail(
                failure.title, failure.feedback, log_path=agent.presentation.log_path))

    @abstractmethod
    def report_failure(self, agent, event) -> None: ...

    def require_confirmation(self) -> StopReason:
        raise QueueActionRefused(
            f"Request not confirmed: {self.failure.failure.feedback}. Inspect its state before another action."
        )


class FailedPromptResult(UnfinishedPromptResult):
    """A negative reply preserves the session, not a claim that input was accounted for."""

    def report_failure(self, agent, event) -> None:
        agent.events.publish(event)


class ResolvedFailurePromptResult(ConfirmedPromptResult, FailedPromptResult):
    """A definite input disposition, including a proved refusal before SDK invocation."""

    def settle_submission(self, execution) -> None:
        execution.state.response_failed(execution, self.failure.failure)


class UnconfirmedPromptResult(UnfinishedPromptResult):
    """The captured request lost its reply or authority; it grants no retry."""

    def report_failure(self, agent, event) -> None:
        agent.session.record_failure(event)


class QueueSessionRequest(ClientSessionRequest):
    """A queue mutation requires confirmation; an absent reply is never success."""

    def resolve(self, outcome: PromptResult) -> PromptResult:
        outcome.require_confirmation()
        return outcome


class ClientRequestOwner:
    def __init__(self, agent):
        self.agent = agent

    def session_request(self, session_id):
        request = ClientSessionRequest(self.agent, session_id)
        request.require()
        return request
