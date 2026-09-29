"""One submission transaction owns input intent, request identity and draft recovery."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import ClassVar

from agent_comms.acp_extension import QueuePromptRequest, SteerPromptRequest
from agent_comms.declared_family import DeclaredFamily
from toad import jsonrpc, messages
from toad.conversation_turn import AgentTurn, ClientTurn
from toad.widgets.user_input import UserInput


@dataclass(frozen=True)
class InputSubmission(DeclaredFamily, affix="InputSubmission"):
    source_text: str
    priority: ClassVar[int] = 0

    @property
    def text(self):
        return self.source_text.strip()

    @classmethod
    @abstractmethod
    def matches(cls, event, view): ...

    @abstractmethod
    async def execute(self, owner): ...

    @classmethod
    def decode(cls, event, view):
        kind = next(kind for kind in sorted(cls.members_with(InputSubmission),
                                            key=lambda kind: kind.priority, reverse=True)
                    if kind.matches(event, view))
        return kind(event.body)


class NoInputSubmission(InputSubmission):
    priority = -1
    @classmethod
    def matches(cls, event, view):
        return True
    async def execute(self, owner):
        pass


class QueueNowInputSubmission(InputSubmission):
    priority = 100
    @classmethod
    def matches(cls, event, view):
        if event.shell or event.body.strip():
            return False
        return event.immediate and view.queue_supported
    async def execute(self, owner):
        projection = owner.view.queue_projection
        if projection.status == 'available' and projection.items:
            owner.requested_queue = projection.items[0]
            owner.publish_pending()
            owner.send_now()


class ShellInputSubmission(InputSubmission):
    priority = 90
    @classmethod
    def matches(cls, event, view):
        return event.shell and bool(event.body.strip())
    async def execute(self, owner):
        view = owner.view
        view.transcript.invalidate()
        shell = view.shell
        if await shell.is_busy():
            shell.focus_output()
            await shell.send_input(self.source_text, paste=True)
        else:
            view.run_worker(partial(view.input_histories.shell.record, self.source_text), group='history')
            await view.post_shell(self.source_text)
        view.jump_to_latest()


class AgentInputSubmission(InputSubmission):
    pending_text = ''

    @property
    @abstractmethod
    def request(self): ...

    async def feedback(self, execution):
        view = execution.owner.view
        await view.post(UserInput(self.text))
        if not execution.current:
            return
        view.jump_to_latest()
        await view._auto_name_from_prompt(self.text)
        if not execution.current:
            return
        waiting = 'Waiting for replies…' if self.text.startswith(('@', '#', '!relay ')) else 'Thinking…'
        view.post_message(messages.SessionUpdate(state='busy', summary=waiting.rstrip('…')))
        view.activity = waiting
        await asyncio.sleep(0)

    async def execute(self, owner):
        view = owner.view
        view.transcript.invalidate()
        if self.text.startswith('/') and await view.slash_command(self.text):
            return
        if view.agent is None:
            return
        execution = SubmissionExecution(owner, self, view.agent)
        owner.active.append(execution)
        owner.publish_pending()
        view.run_worker(partial(view.input_histories.prompt.record, self.source_text), group='history')
        try:
            await self.feedback(execution)
            if execution.current:
                return view.run_worker(partial(execution.send), group='conversation-submission')
            else:
                owner.finish(execution)
        except BaseException:
            owner.finish(execution)
            raise


class OrdinaryInputSubmission(AgentInputSubmission):
    @classmethod
    def matches(cls, event, view):
        return not event.shell and bool(event.body.strip())
    @property
    def request(self):
        return QueuePromptRequest(self.text)


class DeferredInputSubmission(OrdinaryInputSubmission):
    priority = 70
    @classmethod
    def matches(cls, event, view):
        if not super().matches(event, view):
            return False
        return view.turns.owner.busy and view.queue_supported and not event.immediate
    @property
    def request(self):
        return QueuePromptRequest(self.text, True)
    async def feedback(self, execution):
        execution.owner.view.flash('Queue request sent; awaiting authoritative queue state')


class ImmediateInputSubmission(OrdinaryInputSubmission):
    priority = 80
    @classmethod
    def matches(cls, event, view):
        if not super().matches(event, view):
            return False
        return event.immediate and view.queue_supported
    @property
    def request(self):
        return SteerPromptRequest(self.text)
    @property
    def pending_text(self):
        return self.text


class SubmissionExecution:
    """Immutable source binding and the real outstanding local request."""
    def __init__(self, owner, submission, agent):
        self.owner, self.submission, self.agent = owner, submission, agent
        self.session_id = agent.session_id
        self.scope = agent.queue_attachment.scope
        self.request = submission.request

    @property
    def current(self):
        view = self.owner.view
        if view.agent is not self.agent or self.agent.session_id != self.session_id:
            return False
        return self.agent.queue_attachment.accepts_request(self.scope)

    async def send(self):
        view = self.owner.view
        local = not self.agent.presentation.uses_managed_turns
        reason = None
        if local:
            view.busy_count += 1
            view.turns.owner = AgentTurn()
        try:
            if view.queue_supported:
                reason = await self.agent.send_prompt(self.submission.text, request=self.request)
            else:
                reason = await self.agent.send_prompt(self.submission.text)
        except (jsonrpc.APIError, jsonrpc.JSONRPCError, OSError, ValueError) as error:
            if self.current:
                from toad.widgets.conversation import INTERNAL_EROR
                from toad.widgets.markdown_note import MarkdownNote
                view.turns.owner = ClientTurn()
                view.activity = ''
                view.activity_started_at = None
                self.owner.restore_draft(self.submission.text)
                await view.post(MarkdownNote(INTERNAL_EROR.replace('$ERROR', str(error) or 'no details were provided'),
                                             classes='-stop-reason'))
        finally:
            self.owner.finish(self)
            if local and self.current:
                view.busy_count -= 1
        if self.current and local:
            view.call_later(self.complete, reason)

    async def complete(self, reason):
        if self.current:
            await self.owner.view.agent_turn_over(reason)


class ConversationSubmissions:
    """Own pending local transactions; remote membership stays with QueueAttachment."""
    def __init__(self, view):
        self.view = view
        self.active: list[SubmissionExecution] = []
        self.requested_queue = None

    async def submit(self, event):
        return await InputSubmission.decode(event, self.view).execute(self)

    def accepts_failure(self, message):
        agent = self.view.agent
        if agent is None or message.agent is not agent:
            return False
        if message.session_id != agent.session_id:
            return False
        return not message.recover_draft or agent.queue_attachment.accepts_request(message.queue_scope)

    def publish_pending(self):
        self.view.delivering_prompt = next((item.submission.pending_text for item in reversed(self.active)
                                           if item.current and item.submission.pending_text), '')
        self.view.sending_queued_prompt = self.requested_queue.text if self.requested_queue else ''

    def finish(self, execution):
        if execution in self.active:
            self.active.remove(execution)
        if execution.current:
            self.publish_pending()

    def reset(self):
        self.active.clear()
        self.requested_queue = None
        self.publish_pending()

    def started(self, item):
        if self.requested_queue and item.input_id == self.requested_queue.input_id:
            self.requested_queue = None
            self.publish_pending()

    def restore_draft(self, text):
        current = self.view.prompt.text
        if text and current != text and not current.endswith('\n\n' + text):
            self.view.prompt.text = '\n\n'.join(filter(None, [current, text]))

    def send_now(self):
        agent = self.view.agent
        session, scope = agent.session_id, agent.queue_attachment.scope
        return self.view.run_worker(partial(self._send_now, agent, session, scope),
                                    group='send-queued-now', exclusive=True)

    async def _send_now(self, agent, session, scope):
        try:
            if await agent.send_now():
                return
        except (jsonrpc.APIError, jsonrpc.JSONRPCError, OSError, ValueError) as error:
            if self.view.agent is agent and agent.session_id == session:
                self.view.flash(f'Send now failed: {error}', style='error')
        if self.view.agent is agent and agent.queue_attachment.accepts_request(scope):
            self.requested_queue = None
            self.publish_pending()
