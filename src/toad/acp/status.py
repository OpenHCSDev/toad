"""Specification-spelled reasons and statuses own toolkit independent facts."""
from agent_comms.declared_family import DeclaredFamily
from dataclasses import dataclass
from acp.schema import ToolCall


class StopReason(DeclaredFamily, affix='StopReason'):
    completed = False
    note = ''


class EndTurnStopReason(StopReason):
    completed = True


class MaxTokensStopReason(StopReason):
    note = '## Maximum tokens reached\n\n$AGENT reached the maximum output tokens for this turn.'


class MaxTurnRequestsStopReason(StopReason):
    note = '## Maximum model requests reached\n\n$AGENT has exceeded the maximum number of model requests in a single turn.'


class RefusalStopReason(StopReason):
    note = '## Agent refusal\n\n$AGENT has refused to continue.'


class CancelledStopReason(StopReason):
    pass


@dataclass(frozen=True)
class ToolCallStatus(DeclaredFamily, affix='ToolCallStatus'):
    call: ToolCall

    @classmethod
    def from_acp(cls, call: ToolCall):
        kind = cls.decode(call.status or PendingToolCallStatus.declared_name)
        return kind(call)

    busy = False
    boundary = False
    completed = False
    failed = False

    @classmethod
    def activity(cls, turns, output, title):
        if cls.busy:
            turns.describe(' '.join(title.splitlines()))
        if cls.boundary:
            output.boundary()


class PendingToolCallStatus(ToolCallStatus):
    busy = True


class InProgressToolCallStatus(ToolCallStatus):
    busy = True


class CompletedToolCallStatus(ToolCallStatus):
    boundary = completed = True


class FailedToolCallStatus(ToolCallStatus):
    boundary = failed = True
