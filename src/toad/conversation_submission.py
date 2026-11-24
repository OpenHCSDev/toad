"""One submission transaction owns input intent, request identity and draft recovery."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import ClassVar

from acp.exceptions import RequestError
from agent_comms.acp_extension import (
    InputStartedUpdate,
    QueuePromptRequest,
    QueueScope,
    SteerPromptRequest,
)
from agent_comms.messaging.message_files import FileUpload
from agent_comms.nominal.declared_family import DeclaredFamily

from toad.acp.agent import Agent
from toad.acp.client_session import ClientSessionRequest
from toad.acp.queue_attachment import QueueActionRefused
from toad.acp.status import StopReason, UnreportedStopReason
from toad.client.bus_submission import (
    BusSubmissions,
    PendingSubmissionPhase,
    SettledSubmissionPhase,
    SubmissionExecution,
    SubmittingPhase,
)
from toad.client.submission import SubmittedText
from toad.command_catalog import CommandCatalog
from toad.core.input_events import UserInputSubmitted
from toad.core_event_carrier import CoreEventMessage
from toad.client.input_decision import InputDecision
from toad.submission_queue import QueueEvidence, QueueSource
from toad.worker_group import InputHistoryRecord


@dataclass(frozen=True)
class InputSubmission(SubmittedText, DeclaredFamily, affix="InputSubmission"):
    source_text: str
    files: tuple[FileUpload, ...]
    priority: ClassVar[int] = 0

    @classmethod
    @abstractmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions): ...

    @abstractmethod
    async def execute(self, owner: ConversationSubmissions): ...

    def started(self, owner: ConversationSubmissions) -> Callable[[], Awaitable[object]]:
        """Take this submission now and return the work still to do. Most kinds do all of it
        later; a message is listed now (`AgentInputSubmission.started`)."""
        return partial(self.execute, owner)

    @classmethod
    def from_event(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        kind = next(
            kind
            for kind in sorted(cls.members_with(InputSubmission), key=lambda kind: kind.priority, reverse=True)
            if kind.matches(event, owner)
        )
        return kind(event.body, event.files)


class NoInputSubmission(InputSubmission):
    priority = -1

    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        return True

    async def execute(self, owner: ConversationSubmissions):
        pass


class QueueNowInputSubmission(InputSubmission):
    priority = 100

    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        if event.shell or event.body.strip():
            return False
        return event.immediate and owner.holds_input

    async def execute(self, owner: ConversationSubmissions):
        owner.send_now()


class ShellInputSubmission(InputSubmission):
    priority = 90

    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        return event.shell and bool(event.body.strip())

    async def execute(self, owner: ConversationSubmissions):
        view = owner.view
        shell = view.shell
        if await shell.is_busy():
            shell.focus_output()
            await shell.send_input(self.source_text, paste=True)
        else:
            InputHistoryRecord.run_on(view, partial(view.input_histories.shell.record, self.source_text))
            await view.post_shell(self.source_text)
        view.jump_to_latest()


class AgentInputSubmission(InputSubmission):
    @property
    @abstractmethod
    def request(self): ...

    async def feedback(self, execution: SubmissionExecution):
        view = execution.owner.view
        await view.turns.binding.present_input(view, self.text)
        if execution.retired:
            return
        view.jump_to_latest()
        await view.auto_name_from_prompt(self.text)
        if execution.retired:
            return
        waiting = "Waiting for replies…" if self.text.startswith(("@", "#", "!relay ")) else "Thinking…"
        view.turns.describe(waiting)
        await asyncio.sleep(0)

    async def execute(self, owner: ConversationSubmissions):
        return await owner.begin(self).prepare()

    def started(self, owner: ConversationSubmissions) -> Callable[[], Awaitable[object]]:
        """Listed in the delivery preview in the call that takes it from the composer: the
        composer's cleared editor and the message's preview row are one frame, never an empty
        one between them (it was listed a worker turn later, after the clear was painted)."""
        start = owner.begin(self)
        owner.publish_pending()
        return start.prepare


class OrdinaryInputSubmission(AgentInputSubmission):
    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        if event.shell:
            return False
        return bool(event.body.strip())

    @property
    def request(self):
        return QueuePromptRequest(self.text)


class DeferredInputSubmission(OrdinaryInputSubmission):
    priority = 70

    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        if not super().matches(event, owner):
            return False
        if event.immediate:
            return False
        view = owner.view
        return view.turns.owner.busy and view.agent_binding.presentation.queue_supported

    @property
    def request(self):
        return QueuePromptRequest(self.text, True)

    async def feedback(self, execution: SubmissionExecution):
        # Native queue/start publications own confirmation and message display.
        pass


class ImmediateInputSubmission(OrdinaryInputSubmission):
    priority = 80

    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        if not super().matches(event, owner):
            return False
        return event.immediate and owner.view.agent_binding.presentation.queue_supported

    @property
    def request(self):
        return SteerPromptRequest(self.text)


class PromptPhase(SubmittingPhase):
    """Whether the agent has started this prompt: until it does, the prompt still shows as submitting."""


class PromptUnstarted(PendingSubmissionPhase, PromptPhase):
    pass


class PromptStarted(SettledSubmissionPhase, PromptPhase):
    pass


class AgentSubmissionExecution(SubmissionExecution):
    """A prompt for this view's ACP agent."""

    submission: AgentInputSubmission

    def __init__(self, owner: ConversationSubmissions, submission: AgentInputSubmission, agent: Agent):
        super().__init__(owner, submission)
        self.agent = agent
        self.authority = ClientSessionRequest(agent, agent.session_id)
        self.scope = agent.queue_attachment.scope
        self.request = submission.request
        self.phase: PromptPhase = PromptUnstarted()

    async def present(self) -> None:
        await self.submission.feedback(self)

    def input_presented(self, started: InputStartedUpdate) -> None:
        if self.current and started.started_request(self.request.input_id):
            self.phase = PromptStarted()

    @property
    def current(self):
        view = self.owner.view
        if view.agent_binding is not self.agent or self.authority.retired:
            return False
        return self.agent.queue_attachment.accepts_request(self.scope)

    def delivering(self) -> tuple[str, ...]:
        queue = self.agent.presentation.queue
        accepted = {row.input_id for row in (*queue.items, *queue.restored)}
        if (self.current and self.agent.presentation.uses_managed_turns
                and self.request.input_id not in accepted):
            return self.phase.submitting(self.submission.text)
        return ()

    async def send(self):
        view = self.owner.view
        managed = self.agent.presentation.uses_managed_turns
        local = not managed
        reason: type[StopReason] = UnreportedStopReason
        if local:
            view.turns.start_client()
        try:
            if self.agent.presentation.queue_supported:
                reason = await self.agent.send_prompt(self.submission.text, request=self.request)
            else:
                reason = await self.agent.send_prompt(self.submission.text)
        except RequestError as error:
            if self.current:
                await view.submission_request_failed(error, self.submission.text)
        finally:
            self.owner.finish(self)
        if self.current and local:
            view.call_later(self.complete, reason)

    async def complete(self, reason: type[StopReason]) -> None:
        if self.current:
            await self.owner.view.agent_turn_over(reason)


class ConversationSubmissions(BusSubmissions):
    """Own pending local transactions; remote membership stays with QueueAttachment."""

    def begin(self, submission: AgentInputSubmission):
        return self.view.begin_submission(self, submission)

    def start(self, submission: AgentInputSubmission, agent: Agent):
        execution = AgentSubmissionExecution(self, submission, agent)
        self.active.append(execution)
        return execution

    @property
    def input_decision(self) -> InputDecision:
        return self.view.operational_sources.input_decision(self.view)

    async def submit(self, event: UserInputSubmitted):
        text = event.body.strip()
        if not event.shell and await CommandCatalog.execute(text, self.view):
            return
        return await InputSubmission.from_event(event, self).execute(self)

    def received(self, event: UserInputSubmitted) -> Callable[[], Awaitable[object]]:
        """What the composer handed over, taken in this call; returns the work still to do.
        Text that may name a command waits for the catalog first, so it runs as `submit`; a
        message is listed now (`InputSubmission.started`)."""
        if not event.shell and CommandCatalog.may_name_command(event.body.strip()):
            return partial(self.submit, event)
        return InputSubmission.from_event(event, self).started(self)

    def accepts_failure(self, message: CoreEventMessage):
        return self.view.agent_binding.accepts_failed_input(message)

    @property
    def queue_evidence(self) -> QueueEvidence:
        return QueueEvidence(
            self.view.agent_binding.presentation, self.submitting, self.view.turns.owner.busy,
            self.view.contents.notification_targets,
            self.view.queue_source.capture_queue_observing(
                self.view.thread_scope.queue_observing,
                self.view.app.coordination_access.observation.queue_observing))

    @property
    def holds_input(self) -> bool:
        return self.view.queue_source.holds_input(self.queue_evidence)

    @property
    def queue_summary(self) -> str:
        return self.view.queue_source.queue_summary(self.queue_evidence)

    @property
    def queue_hint(self) -> str:
        return self.view.queue_source.queue_hint(self.queue_evidence)

    @property
    def queue_projection(self):
        return self.view.agent_binding.presentation.queue

    @property
    def queued_inputs(self):
        """Accepted producer rows not yet handed to their original native body."""
        return self.queue_projection.items

    def native_input_presented(self, started: InputStartedUpdate):
        """Retain this request's actual response while its RPC is outstanding."""
        for execution in self.active:
            execution.input_presented(started)

    def send_now(self):
        source = self.view.queue_source
        evidence = self.queue_evidence
        return self.view.run_worker(
            partial(self._send_now, source, evidence, source.queue_scope(evidence)),
            group="send-queued-now", exclusive=True,
        )

    async def _send_now(self, source: QueueSource, evidence: QueueEvidence, scope: QueueScope) -> None:
        try:
            await source.queue_send_now(evidence, scope)
        except (RequestError, QueueActionRefused) as error:
            self.view.feedback.flash(f"Send now failed: {error}", style="error")
        self.publish_pending()
