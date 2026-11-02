"""Specification-spelled reasons and statuses own toolkit independent facts."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from acp.schema import PromptResponse, ToolCall
from agent_comms.agent_event_updates import AcpToolAction
from agent_comms.nominal.declared_family import DeclaredFamily
from metaclass_registry.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    ToolEndTranscript,
    ToolStartTranscript,
    ToolTranscript,
)

from toad.line_blocks import (
    FailureRole,
    Span,
    SuccessRole,
    Summary,
    ToolArgumentRole,
    ToolVerbRole,
    WorkingRole,
)


class PromptResult(ABC):
    """A request's answer, not an optional SDK stop reason."""

    @abstractmethod
    def require_confirmation(self) -> StopReason: ...

    def publish_failure(self) -> None:
        """A confirmed completion has no failure to publish."""

    def settle_submission(self, execution) -> None:
        execution.state.response_finished(execution)

    async def finish_turn(self, view) -> None:
        """No confirmed completion: release local activity, not a completed turn."""
        view.turns.finish_client()


class ConfirmedPromptResult(PromptResult):
    """An SDK completion or definite input disposition gives this request a known result."""

    def settle_submission(self, execution) -> None:
        execution.state.response_confirmed(execution)


@dataclass(frozen=True)
class StopReason(ConfirmedPromptResult, DeclaredFamily, affix='StopReason'):
    """Only the SDK's declared stop reasons are confirmed prompt completions."""

    response: PromptResponse
    note = ''

    @classmethod
    def from_acp(cls, response: PromptResponse) -> StopReason:
        return cls.member_named(response.stop_reason)(response)

    def require_confirmation(self) -> StopReason:
        """A returned SDK completion confirms a queue mutation."""
        return self

    async def finish_turn(self, view) -> None:
        await view.agent_turn_over(self)

    def record_model_usage(self, view) -> None:
        """Only a successful end-turn records recent model use."""


class EndTurnStopReason(StopReason):
    def record_model_usage(self, view) -> None:
        view.record_model_usage()


class MaxTokensStopReason(StopReason):
    note = '## Maximum tokens reached\n\n$AGENT reached the maximum output tokens for this turn.'


class MaxTurnRequestsStopReason(StopReason):
    note = '## Maximum model requests reached\n\n$AGENT has exceeded the maximum number of model requests in a single turn.'


class RefusalStopReason(StopReason):
    note = '## Agent refusal\n\n$AGENT has refused to continue.'


class CancelledStopReason(StopReason):
    pass


@dataclass(frozen=True)
class ToolCallStatus(MroDispatch, DeclaredFamily, affix='ToolCallStatus'):
    call: ToolCall

    @classmethod
    def from_acp(cls, call: ToolCall):
        kind = cls.member_named(call.status) if call.status else PendingToolCallStatus
        return kind(call)

    @classmethod
    def from_transcript(cls, events: tuple[ToolTranscript, ...]):
        """Acquire one recorded call before its fragment enters native layout.

        The fragment producer owns grouping and event order. Native consumers
        borrow the final ACP state, including an end without its earlier start.
        """
        first = events[0]
        call = ToolCall(tool_call_id=first.tool_call_id, title=first.title,
                        kind=AcpToolAction.kind(first.kind), status='completed')
        consumer = cls(call)
        for event in events:
            consumer.dispatch_sync(event)
        return cls.from_acp(call)

    @handles(ToolStartTranscript)
    def recorded_start(self, event: ToolStartTranscript):
        self.call.status = 'in_progress'
        self.call.title = event.title
        self.call.kind = AcpToolAction.kind(event.kind)
        self.call.raw_input = event.raw_input

    @handles(ToolEndTranscript)
    def recorded_end(self, event: ToolEndTranscript):
        self.call.status = "completed" if event.ok else "failed"
        # Saved output stays on its already-decoded result, not a JSON/SDK copy.

    def project_output(self, parts, project):
        """Only completed sends may replace reported output with a proved body."""
        return project(parts) if self.completed else parts

    busy = False
    boundary = False
    completed = False
    failed = False
    summary_suffix = ''
    summary_role = WorkingRole

    @property
    def title(self) -> str:
        return self.call.title or 'Tool'

    @property
    def summary(self) -> Summary:
        """The argument may clip; the outcome keeps its space and meaning."""
        verb, separator, argument = self.title.partition(' ')
        return Summary((Span(verb, ToolVerbRole), Span(separator + argument, ToolArgumentRole)),
                       kept=(Span(self.summary_suffix, self.summary_role),))

    @classmethod
    def activity(cls, turns, output, title):
        if cls.busy:
            turns.describe(' '.join(title.splitlines()))
        if cls.boundary:
            output.boundary()


class PendingToolCallStatus(ToolCallStatus):
    busy = True
    summary_suffix = ' ⌛'


class InProgressToolCallStatus(ToolCallStatus):
    busy = True
    summary_suffix = ' · running'


class CompletedToolCallStatus(ToolCallStatus):
    boundary = completed = True
    summary_suffix = ' ✔'
    summary_role = SuccessRole


class FailedToolCallStatus(ToolCallStatus):
    boundary = failed = True
    summary_suffix = ' · failed'
    summary_role = FailureRole
