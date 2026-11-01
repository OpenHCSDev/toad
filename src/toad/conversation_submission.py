"""One submission transaction owns input intent, request identity and draft recovery."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from acp.exceptions import RequestError
from agent_comms.acp_extension import (
    InputStartedUpdate,
    QueuePromptRequest,
    QueueScope,
    SteerPromptRequest,
)
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.delivery_failure import delivery_failure
from agent_comms.errors import CommittedMessageError, HumanSendError, HumanSendRefusedError, RelationViolationError, RouteChangedError
from agent_comms.messages import Message

from toad import messages
from toad.command_catalog import CommandCatalog
from toad.acp.queue_attachment import QueueActionRefused
from toad.queue_capability import QueueActions, QueueEvidence
from toad.core.input_events import UserInputSubmitted
from toad.core_event_carrier import CoreEventMessage
from toad.input_decision import InputDecision, InputRefused
from toad.widgets.prompt import Prompt

@dataclass(frozen=True)
class InputSubmission(DeclaredFamily, affix="InputSubmission"):
    source_text: str

    @property
    def text(self):
        return self.source_text.strip()

    @classmethod
    @abstractmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions): ...

    @abstractmethod
    async def execute(self, owner: ConversationSubmissions): ...

    @classmethod
    def from_event(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        kind = next(
            kind
            for kind in sorted(cls.members_with(InputSubmission), key=lambda kind: len(kind.__mro__), reverse=True)
            if kind.matches(event, owner)
        )
        return kind(event.body)


class NoInputSubmission(InputSubmission):
    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        return not event.body.strip()

    async def execute(self, owner: ConversationSubmissions):
        pass


class QueueNowInputSubmission(NoInputSubmission):
    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        if event.shell or event.body.strip():
            return False
        return event.immediate and owner.view.queue_source.queue_actions_available(owner.view.agent_binding.presentation)

    async def execute(self, owner: ConversationSubmissions):
        projection = owner.queue_projection
        if projection.items:
            owner.send_now()


class ShellInputSubmission(InputSubmission):
    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        return event.shell and bool(event.body.strip())

    async def execute(self, owner):
        view = owner.view
        shell = view.shell
        if await shell.is_busy():
            shell.focus_output()
            await shell.send_input(self.source_text, paste=True)
        else:
            view.run_worker(partial(view.input_histories.shell.record, self.source_text), group="history")
            await view.post_shell(self.source_text)
        view.jump_to_latest()


class SubmissionStart(ABC):
    """The result of acquiring a submission's source, not an optional request."""

    @abstractmethod
    async def prepare(self): ...


class UnboundSubmissionStart(SubmissionStart):
    def __init__(
        self, owner: ConversationSubmissions, submission: PromptInputSubmission, refusal: InputRefused
    ):
        self.owner, self.submission, self.refusal = owner, submission, refusal

    async def prepare(self):
        self.owner.view.delivery_refused(
            self.refusal.message,
            self.submission.source_text,
        )


class PromptInputSubmission(InputSubmission):
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
        view = owner.view
        return await owner.begin(self).prepare()


class OrdinaryInputSubmission(PromptInputSubmission):
    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        if event.shell:
            return False
        return bool(event.body.strip())

    @property
    def request(self):
        return QueuePromptRequest(self.text)


class DeferredInputSubmission(OrdinaryInputSubmission):
    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        if not super().matches(event, owner):
            return False
        if event.immediate:
            return False
        view = owner.view
        return view.queue_source.defers_input(view)

    @property
    def request(self):
        return QueuePromptRequest(self.text, True)

    async def feedback(self, execution: SubmissionExecution):
        # Native queue/start publications own confirmation and message display.
        pass


class ImmediateInputSubmission(OrdinaryInputSubmission):
    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        if not super().matches(event, owner):
            return False
        return event.immediate and owner.view.queue_source.queue_actions_available(owner.view.agent_binding.presentation)

    @property
    def request(self):
        return SteerPromptRequest(self.text)


class SendState:
    """One transaction's local outcome; widgets only draw this answer."""

    reason = ""

    def settle(self, execution) -> None:
        execution.owner.retire(execution)

    def acknowledged_by(self, view) -> bool:
        return False

    def response_finished(self, execution) -> None:
        """A retained outcome already names the transaction's answer."""

    def response_confirmed(self, execution) -> None:
        """A confirmed reply settles input; an absent reply never calls this."""
        execution.enter(NoSend())

    def local_intent(self, execution, accepted) -> tuple[str, ...]:
        return ()


class NoSend(SendState):
    pass


class RetainedSend(SendState):
    def settle(self, execution) -> None:
        """A pending, undrawn or UNKNOWN result keeps its original transaction."""


class CheckingSend(RetainedSend):
    reason = "Checking source; do not retry"

    def response_finished(self, execution) -> None:
        execution.delivery_refused(
            "Request ended before handing input to its source", execution.submission.source_text,
        )

    def local_intent(self, execution, accepted) -> tuple[str, ...]:
        return () if execution.accepted(accepted) else (execution.submission.text,)


class SendPending(CheckingSend):
    reason = "Send pending; do not retry"

    def response_finished(self, execution) -> None:
        execution.delivery_blocked(
            "Request ended without a known outcome; inspect the source, do not retry",
            execution.submission.source_text,
        )


@dataclass(frozen=True)
class SentAwaitingSource(RetainedSend):
    root: Path
    sent: Message

    @property
    def reason(self) -> str:
        return f"Sent {self.root}/{self.sent.seq}/{self.sent.message_id}; waiting for source acknowledgement, do not retry"

    def acknowledged_by(self, view) -> bool:
        return view.queue_source.contains_message(view, self.root, self.sent)


@dataclass(frozen=True)
class SendBlocked(RetainedSend):
    description: str

    @property
    def reason(self) -> str:
        return f"Send blocked: {self.description}"


class SubmissionExecution(SubmissionStart):
    """Shared history, worker and outcome lifetime over an immutable source binding."""

    worker_group = __qualname__

    def __init__(self, owner: ConversationSubmissions, submission: PromptInputSubmission):
        self.owner, self.submission = owner, submission
        self.state: SendState = CheckingSend()

    @property
    @abstractmethod
    def current(self) -> bool: ...

    @property
    def retired(self):
        return not self.current

    def enter(self, state: SendState) -> None:
        self.state = state
        self.owner.view.refresh_submission_state()

    def accepted(self, accepted) -> bool:
        return False

    def native_input_presented(self, started: InputStartedUpdate) -> None:
        """A non-native source has no native start to observe."""

    async def feedback(self):
        """Only a source's own acceptance can confirm its input."""

    async def prepare(self):
        view, submission = self.owner.view, self.submission
        self.owner.publish_pending()
        view.run_worker(partial(view.input_histories.prompt.record, submission.source_text), group="history")
        try:
            worker = view.run_worker(partial(self.send), group=self.worker_group)
            worker._add_done_callback(lambda _worker: self.finish())
            return worker
        except BaseException:
            self.finish()
            raise

    @abstractmethod
    async def deliver(self): ...

    async def send(self):
        await self.feedback()
        if self.current:
            await self.deliver()
        else:
            self.delivery_refused("Message source changed; reopen this view", self.submission.source_text)

    def finish(self) -> None:
        self.state.response_finished(self)
        self.owner.finish(self)

    def delivery_blocked(self, description: str, body: str) -> None:
        self.enter(SendBlocked(description))
        self.owner.view.prompt.restore_draft(body)
        self.owner.view.feedback.flash(self.state.reason, style="error")

    def delivery_refused(self, description: str, body: str) -> None:
        self.enter(NoSend())
        self.owner.view.delivery_refused(description, body)


class MessageSubmissionExecution(SubmissionExecution):
    """An original Core publication, including a worker whose outcome is UNKNOWN."""

    def __init__(self, owner: ConversationSubmissions, submission: PromptInputSubmission,
                 root: Path, conversation, current: Callable[[], bool],
                 present: Callable[[Message], Awaitable[None]]):
        super().__init__(owner, submission)
        self.root, self.conversation = root, conversation
        self.source_current, self.present = current, present

    @property
    def current(self) -> bool:
        return self.source_current()

    async def deliver(self):
        view, body = self.owner.view, self.submission.source_text
        try:
            comms = await view.app.coordination_access.transcripts.service(self.root)
            read_only = await view.app.preparation.run_thread(self.conversation.read_only, comms)
            if read_only:
                raise HumanSendRefusedError(RelationViolationError("Read-only saved view"))
            route_current = await view.app.preparation.run_thread(
                lambda: view.app.coordination_access.current(self.root))
            if not route_current or not self.current:
                raise HumanSendRefusedError(RelationViolationError("Message route changed; reopen this view"))
            self.enter(SendPending())
            task = asyncio.create_task(asyncio.to_thread(
                comms.messaging.send_user_message, self.conversation.send_target(), body,
                worktree=view.project_path))
            try:
                sent = await asyncio.shield(task)
            except asyncio.CancelledError:
                self.delivery_blocked("Send cancelled while worker may still write; outcome UNKNOWN, inspect the bus, do not retry", body)
                task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
                return
            except CommittedMessageError as error:
                sent = error.record
            self.enter(SentAwaitingSource(comms.root, sent))
        except asyncio.CancelledError:
            self.delivery_refused("Cancelled before sending", body)
            raise
        except (HumanSendError, RouteChangedError) as error:
            delivery_failure(error).present(self, body)
            return
        if self.current:
            await self.present(sent)


class ConversationSubmissions:
    """Own pending local transactions; remote membership stays with QueueAttachment."""

    def __init__(self, view):
        self.view = view
        self.active: list[SubmissionExecution] = []

    @property
    def retains_surface(self) -> bool:
        """Pending, unacknowledged and UNKNOWN intent still owns this view's resources."""
        return bool(self.active)

    async def close(self) -> None:
        workers = self.view.workers.cancel_group(self.view, SubmissionExecution.worker_group)
        # Worker reports errors itself; retirement waits for every completion,
        # including cancellation, before the view releases its draft resources.
        await asyncio.gather(*(worker.wait() for worker in workers), return_exceptions=True)

    def begin(self, submission: PromptInputSubmission):
        return self.view.queue_source.begin_submission(self, submission)

    def unbound(self, submission: PromptInputSubmission, refusal: InputRefused):
        return UnboundSubmissionStart(self, submission, refusal)

    def start(self, execution: SubmissionExecution):
        self.active.append(execution)
        self.view.refresh_submission_state()
        return execution

    def start_message(self, submission: PromptInputSubmission, root: Path, conversation,
                      current: Callable[[], bool], present: Callable[[Message], Awaitable[None]]):
        return self.start(MessageSubmissionExecution(self, submission, root, conversation, current, present))

    @property
    def send_block_reason(self) -> str:
        return next((item.state.reason for item in self.active if item.state.reason), "")

    @property
    def input_decision(self) -> InputDecision:
        return self.view.queue_source.input_decision(self.view)

    async def submit(self, event: UserInputSubmitted):
        text = event.body.strip()
        if not event.shell and text.startswith("/") and await CommandCatalog.execute(text, self.view):
            return
        if self.send_block_reason:
            self.view.delivery_refused(self.send_block_reason, event.body)
            return
        return await InputSubmission.from_event(event, self).execute(self)

    def accepts_failure(self, message: CoreEventMessage):
        return self.view.agent_binding.accepts_failed_input(message)

    @property
    def queue_evidence(self) -> QueueEvidence:
        return QueueEvidence(
            self.view.agent_binding.presentation, self.delivering,
            self.send_block_reason, self.view.contents.notification_targets)

    @property
    def queue_summary(self) -> str:
        return self.view.queue_source.queue_summary(self.queue_evidence)

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
        return tuple(text for item in self.active if item.current
                     for text in item.state.local_intent(item, accepted))

    def native_input_presented(self, started: InputStartedUpdate):
        """Retain this request's actual response while its RPC is outstanding."""
        for execution in self.active:
            execution.native_input_presented(started)

    def publish_pending(self):
        if (prompt := self.view.query_one_optional(Prompt)) is not None:
            prompt.sync_queue()

    def retire(self, execution: SubmissionExecution) -> None:
        if execution in self.active:
            self.active.remove(execution)

    def finish(self, execution: SubmissionExecution):
        execution.state.settle(execution)
        self.publish_pending()

    def settle_acknowledged(self) -> None:
        for execution in tuple(self.active):
            if execution.state.acknowledged_by(self.view):
                execution.enter(NoSend())
                self.finish(execution)

    def send_now(self):
        source = self.view.queue_source
        presentation = self.view.agent_binding.presentation
        return self.view.run_worker(
            partial(self._send_now, source, presentation,
                    source.queue_scope(presentation)),
            group="send-queued-now", exclusive=True,
        )

    async def _send_now(self, source: QueueActions, presentation, scope: QueueScope) -> None:
        try:
            await source.queue_send_now(presentation, scope)
        except (RequestError, QueueActionRefused) as error:
            self.view.feedback.flash(f"Send now failed: {error}", style="error")
        self.publish_pending()
