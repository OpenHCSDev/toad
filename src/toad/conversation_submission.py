"""One submission transaction owns input intent, request identity and draft recovery."""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import ClassVar

from agent_comms.acp_extension import InputStartedUpdate, QueuePromptRequest, SteerPromptRequest
from agent_comms.declared_family import DeclaredFamily
from toad import jsonrpc, messages
from toad.acp.client_session import ClientSessionRequest
from agent_comms.acp_extension import PendingQueueProjection
from toad.widgets.prompt import Prompt
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
    def from_event(cls, event, view):
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
        projection = owner.queue_projection
        if projection.status == 'available' and projection.items:
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
    @property
    @abstractmethod
    def request(self): ...

    async def feedback(self, execution):
        view = execution.owner.view
        await view.turns.binding.present_input(view, self.text)
        if execution.retired:
            return
        view.jump_to_latest()
        await view._auto_name_from_prompt(self.text)
        if execution.retired:
            return
        waiting = 'Waiting for replies…' if self.text.startswith(('@', '#', '!relay ')) else 'Thinking…'
        view.turns.describe(waiting)
        await asyncio.sleep(0)

    async def execute(self, owner):
        view = owner.view
        view.transcript.invalidate()
        if self.text.startswith('/') and await view.command_catalog.execute(self.text, view):
            return
        execution = owner.begin(self)
        if execution is None:
            return
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
        if event.shell:
            return False
        return bool(event.body.strip())
    @property
    def request(self):
        return QueuePromptRequest(self.text)


class DeferredInputSubmission(OrdinaryInputSubmission):
    priority = 70
    @classmethod
    def matches(cls, event, view):
        if not super().matches(event, view):
            return False
        if event.immediate:
            return False
        return view.turns.owner.busy and view.queue_supported
    @property
    def request(self):
        return QueuePromptRequest(self.text, True)
    async def feedback(self, execution):
        # Native queue/start publications own confirmation and message display.
        pass


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

class SubmissionExecution:
    """Immutable source binding and the real outstanding local request."""
    def __init__(self, owner, submission, agent):
        self.owner, self.submission, self.agent = owner, submission, agent
        self.authority = ClientSessionRequest(agent, agent.session_id)
        self.scope = agent.queue_attachment.scope
        self.request = submission.request
        self.started_receipt: InputStartedUpdate | None = None

    @property
    def current(self):
        view = self.owner.view
        if view.agent is not self.agent or self.authority.retired:
            return False
        return self.agent.queue_attachment.accepts_request(self.scope)

    @property
    def retired(self):
        return not self.current

    async def send(self):
        view = self.owner.view
        managed = self.agent.presentation.uses_managed_turns
        local = not managed
        reason = None
        if local:
            view.turns.start_client()
        try:
            if view.queue_supported:
                reason = await self.agent.send_prompt(self.submission.text, request=self.request)
            else:
                reason = await self.agent.send_prompt(self.submission.text)
        except (jsonrpc.APIError, jsonrpc.JSONRPCError, OSError, ValueError) as error:
            if self.current:
                from toad.widgets.conversation import INTERNAL_EROR
                from toad.widgets.markdown_note import MarkdownNote
                view.turns.finish_client()
                self.owner.restore_draft(self.submission.text)
                await view.post(MarkdownNote(INTERNAL_EROR.replace('$ERROR', str(error) or 'no details were provided'),
                                             classes='-stop-reason'))
        finally:
            self.owner.finish(self)
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

    def begin(self, submission):
        agent = self.view.agent
        if agent is None:
            return None
        execution = SubmissionExecution(self, submission, agent)
        self.active.append(execution)
        return execution

    async def submit(self, event):
        return await InputSubmission.from_event(event, self.view).execute(self)

    def accepts_failure(self, message):
        agent = self.view.agent
        if agent is None or message.publisher is not agent:
            return False
        if message.event.session_id != agent.session_id:
            return False
        if message.event.recover_draft:
            return agent.queue_attachment.accepts_request(message.event.queue_scope)
        return True

    @property
    def queue_projection(self):
        agent = self.view.agent
        return agent.presentation.queue if agent is not None else PendingQueueProjection()

    @property
    def queued_inputs(self):
        """Accepted producer rows not yet handed to their original native body."""
        claims = tuple(block.commit_claim for block in self.view.contents.query(UserInput))
        return tuple(row for row in self.queue_projection.items
                     if not any(claim.represents_input(row.input_id) for claim in claims))

    @property
    def delivering(self):
        queue = self.queue_projection
        accepted = {row.input_id for row in (*queue.items, *queue.restored)}
        return tuple(item.submission.text for item in self.active
                     if item.current and item.agent.presentation.uses_managed_turns
                     and item.request.input_id not in accepted
                     and item.started_receipt is None)

    def native_input_presented(self, receipt: InputStartedUpdate):
        """Retain this request's actual response while its RPC is outstanding."""
        for execution in self.active:
            if execution.current and execution.request.input_id == receipt.input_id:
                execution.started_receipt = receipt

    def publish_pending(self):
        if (prompt := self.view.query_one_optional(Prompt)) is not None:
            prompt.sync_queue()

    def finish(self, execution):
        if execution in self.active:
            self.active.remove(execution)
        if execution.current:
            self.publish_pending()

    def reset(self):
        self.active.clear()
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
            if await agent.controller.send_now():
                return
        except (jsonrpc.APIError, jsonrpc.JSONRPCError, OSError, ValueError) as error:
            if self.view.agent is agent and agent.session_id == session:
                self.view.flash(f'Send now failed: {error}', style='error')
        if self.view.agent is agent and agent.queue_attachment.accepts_request(scope):
            self.publish_pending()
