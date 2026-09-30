"""Specification-spelled reasons and statuses own their presentation behavior."""
from agent_comms.declared_family import DeclaredFamily
from dataclasses import dataclass
from acp.schema import ToolCall
from textual.content import Content
from toad.pill import pill


class StopReason(DeclaredFamily, affix='StopReason'):
    completed = False
    note = ''

    @classmethod
    async def present(cls, view):
        if cls.note:
            from toad.widgets.markdown_note import MarkdownNote
            await view.post(MarkdownNote(cls.note.replace('$AGENT', (view.agent_title or 'agent').title()), classes='-stop-reason'))


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
    def header(cls, view):
        return Content()

    @classmethod
    def activity(cls, view, title):
        from toad import messages
        if cls.busy:
            view.turns.describe(' '.join(title.splitlines()))
        if cls.boundary:
            view.output.boundary()


class PendingToolCallStatus(ToolCallStatus):
    busy = True

    @classmethod
    def header(cls, view):
        return Content(' ⌛')


class InProgressToolCallStatus(ToolCallStatus):
    busy = True

    @classmethod
    def header(cls, view):
        return Content.assemble(' ', pill('running', '$warning-muted', '$warning', filled=not view.app.theme.startswith('ansi-')))


class CompletedToolCallStatus(ToolCallStatus):
    boundary = completed = True

    @classmethod
    def header(cls, view):
        return Content.from_markup(' [$success]✔')


class FailedToolCallStatus(ToolCallStatus):
    boundary = failed = True

    @classmethod
    def header(cls, view):
        return Content.assemble(' ', pill('failed', '$error-muted', '$error', filled=not view.app.theme.startswith('ansi-')))
