"""One submission transaction owns input intent, request identity and draft recovery."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import ClassVar

from agent_comms.acp_extension import InputStartedUpdate, QueuePromptRequest, SteerPromptRequest
from agent_comms.declared_family import DeclaredFamily
from toad import messages
from acp.exceptions import RequestError
from toad.acp.client_session import ClientSessionRequest
from agent_comms.acp_extension import PendingQueueProjection
from toad.widgets.prompt import Prompt
from toad.command_catalog import CommandCatalog


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
        return event.immediate and view.agent_binding.presentation.queue_supported
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
        view.transcript.invalidate_publications()
        shell = view.shell
        if await shell.is_busy():
            shell.focus_output()
            await shell.send_input(self.source_text, paste=True)
        else:
            view.run_worker(partial(view.input_histories.shell.record, self.source_text), group='history')
            await view.post_shell(self.source_text)
        view.jump_to_latest()


class SubmissionStart(ABC):
    """The result of acquiring a submission's source, not an optional request."""

    @abstractmethod
    async def prepare(self): ...


class UnboundSubmissionStart(SubmissionStart):
    def __init__(self, owner, submission):
        self.owner, self.submission = owner, submission

    async def prepare(self):
        self.owner.view.delivery_refused(
            "No connected owner; your input has not been submitted", self.submission.source_text)


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
        await view.auto_name_from_prompt(self.text)
        if execution.retired:
            return
        waiting = 'Waiting for replies…' if self.text.startswith(('@', '#', '!relay ')) else 'Thinking…'
        view.turns.describe(waiting)
        await asyncio.sleep(0)

    async def execute(self, owner):
        view = owner.view
        view.transcript.invalidate_publications()
        return await owner.begin(self).prepare()


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
        return view.turns.owner.busy and view.agent_binding.presentation.queue_supported
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
        return event.immediate and view.agent_binding.presentation.queue_supported
    @property
    def request(self):
        return SteerPromptRequest(self.text)

class SubmissionExecution(SubmissionStart):
    """Immutable source binding and the real outstanding local request."""
    def __init__(self, owner, submission, agent):
        self.owner, self.submission, self.agent = owner, submission, agent
        self.authority = ClientSessionRequest(agent, agent.session_id)
        self.scope = agent.queue_attachment.scope
        self.request = submission.request
        self.started_update: InputStartedUpdate | None = None

    async def prepare(self):
        owner, submission = self.owner, self.submission
        view = owner.view
        owner.publish_pending()
        view.run_worker(partial(view.input_histories.prompt.record, submission.source_text), group='history')
        try:
            await submission.feedback(self)
            if self.current:
                return view.run_worker(partial(self.send), group='conversation-submission')
            owner.finish(self)
        except BaseException:
            owner.finish(self)
            raise

    @property
    def current(self):
        view = self.owner.view
        if view.agent_binding is not self.agent or self.authority.retired:
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
            if view.agent_binding.presentation.queue_supported:
                reason = await self.agent.send_prompt(self.submission.text, request=self.request)
            else:
                reason = await self.agent.send_prompt(self.submission.text)
        except (RequestError, OSError, ValueError) as error:
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
        return self.view.agent_binding.begin_submission(self, submission)

    def unbound(self, submission):
        return UnboundSubmissionStart(self, submission)

    def start(self, submission, agent):
        execution = SubmissionExecution(self, submission, agent)
        self.active.append(execution)
        return execution

    @property
    def ready(self):
        return self.view.operational_sources.input_ready(self.view)

    @property
    def unavailable_reason(self):
        return self.view.operational_sources.unavailable_reason(self.view)

    async def submit(self, event):
        text = event.body.strip()
        if not event.shell and text.startswith('/') and await CommandCatalog.execute(text, self.view):
            return
        return await self.view.operational_sources.submit(self, event)

    def accepts_failure(self, message):
        return self.view.agent_binding.accepts_failed_input(message)

    @property
    def queue_projection(self):
        return self.view.agent_binding.presentation.queue

    @property
    def queued_inputs(self):
        """Accepted producer rows not yet handed to their original native body."""
        return self.queue_projection.items

    @property
    def delivering(self):
        queue = self.queue_projection
        accepted = {row.input_id for row in (*queue.items, *queue.restored)}
        return tuple(item.submission.text for item in self.active
                     if item.current and item.agent.presentation.uses_managed_turns
                     and item.request.input_id not in accepted
                     and item.started_update is None)

    def native_input_presented(self, started: InputStartedUpdate):
        """Retain this request's actual response while its RPC is outstanding."""
        for execution in self.active:
            if execution.current and execution.request.input_id == started.input_id:
                execution.started_update = started

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
        return self.view.agent_binding.send_now(self)

    def send_bound_now(self, agent):
        session, scope = agent.session_id, agent.queue_attachment.scope
        return self.view.run_worker(partial(self._send_now, agent, session, scope),
                                    group='send-queued-now', exclusive=True)

    async def _send_now(self, agent, session, scope):
        try:
            if await agent.controller.send_now():
                return
        except (RequestError, OSError, ValueError) as error:
            if self.view.agent_binding is agent and agent.session_id == session:
                self.view.flash(f'Send now failed: {error}', style='error')
        if self.view.agent_binding is agent and agent.queue_attachment.accepts_request(scope):
            self.publish_pending()
