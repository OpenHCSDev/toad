"""One submission transaction owns input intent, request identity and draft recovery."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Container
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.worker import Worker

from acp.exceptions import RequestError
from agent_comms.acp_extension import (
    InputStartedUpdate,
    QueueItem,
    QueuePromptRequest,
    QueueScope,
    SteerPromptRequest,
)
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import InputId
from agent_comms.delivery_failure import delivery_failure
from agent_comms.errors import CommittedMessageError, HumanSendError, HumanSendRefusedError, RelationViolationError, RouteChangedError
from agent_comms.messages import Message
from agent_comms.comms import Comms

from toad import messages
from agent_comms.acp_failure import ACPFailure
from toad.acp.queue_attachment import QueueActionRefused
from toad.acp.status import PromptSubmissionOutcome, PromptTurnTarget
from toad.queue_capability import QueueActions, QueueEvidence, QueueView
from toad.shell_source import ShellOperationalSource
from toad.line_blocks import MutedRole, Span
from toad.notification_status import DetailLines
from toad.core.input_events import UserInputSubmitted
from toad.input_decision import InputDecision, InputRefused, InputSourceUnavailable
from toad.input_history import InputHistory, InputHistories
from agent_comms.repo import Checkout
from toad.conversation_turn import InputPresentation
from toad.delivery_failure_view import DeliveryFailureView
from toad.widgets.message_notifications import HistoryNotifications
from toad.message_destination import MessageDestination

if TYPE_CHECKING:
    from toad.transcript_publication import TranscriptPresentation
    from toad.widgets.history_anchor import HistoryWindow


@dataclass(frozen=True, eq=False)
class BusSubmissionSource:
    """The original BUS and destination captured by a message source."""

    comms: Comms
    conversation: MessageDestination


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
        return event.immediate and owner.queue_source.send_now_available(owner)

    async def execute(self, owner: ConversationSubmissions):
        projection = owner.queue_projection
        if projection.items:
            owner.send_now()


class ShellInputSubmission(InputSubmission):
    @classmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        return event.shell and bool(event.body.strip())

    async def execute(self, owner: ConversationSubmissions):
        view = owner
        shell = view.shell
        if await shell.is_busy():
            shell.focus_output()
            await shell.send_input(self.source_text, paste=True)
        else:
            owner.record_history(view.input_histories.shell, self.source_text)
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
        self.owner.delivery_refused(
            self.refusal.message,
            self.submission.source_text,
        )


class PromptInputSubmission(InputSubmission):
    @property
    @abstractmethod
    def request(self): ...

    async def feedback(self, execution: SubmissionExecution):
        view = execution.owner
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
        view = owner
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
        return event.immediate and owner.queue_source.send_now_available(owner)

    @property
    def request(self):
        return SteerPromptRequest(self.text)


class SendState:
    """One transaction's local outcome; widgets only draw this answer."""

    @property
    def reason(self) -> str:
        return ""

    def settle(self, execution: SubmissionExecution) -> None:
        execution.owner.retire(execution)

    def acknowledged_by(self, view: ConversationSubmissions) -> bool:
        return False

    def response_finished(self, execution: SubmissionExecution) -> None:
        """A retained outcome already names the transaction's answer."""

    def response_failed(self, execution: SubmissionExecution, failure: ACPFailure) -> None:
        """An observed input acknowledgement is not undone by a failed reply."""

    def response_confirmed(self, execution: SubmissionExecution) -> None:
        """A confirmed input disposition settles input, not merely an RPC reply."""
        execution.enter(NoSend())

    def presented(self, execution: SubmissionExecution, evidence: SendState) -> None:
        """An in-flight request retains actual input acknowledgement until its reply."""
        execution.enter(evidence)

    def local_intent(self, execution: SubmissionExecution, accepted: Container[InputId]) -> tuple[str, ...]:
        return ()

    async def present_written(self, execution: SubmissionExecution) -> None:
        """Only a definite original publication supplies a message to present."""

    def waiter_cancelled(self, execution: SubmissionExecution) -> None:
        """Cancellation cannot undo an already definite completion."""


class NoSend(SendState):
    pass


class RetainedSend(SendState):
    def settle(self, execution: SubmissionExecution) -> None:
        """A pending, undrawn or UNKNOWN result keeps its original transaction."""


class CheckingSend(RetainedSend):
    reason = "Checking source; do not retry"

    def response_failed(self, execution: SubmissionExecution, failure: ACPFailure) -> None:
        execution.delivery_refused(failure.feedback, execution.submission.source_text)

    def response_finished(self, execution: SubmissionExecution) -> None:
        execution.delivery_refused(
            "Request ended before handing input to its source", execution.submission.source_text,
        )

    def local_intent(self, execution: SubmissionExecution, accepted: Container[InputId]) -> tuple[str, ...]:
        return () if execution.accepted(accepted) else (execution.submission.text,)


class SendPending(CheckingSend):
    reason = "Send pending; do not retry"

    def waiter_cancelled(self, execution: SubmissionExecution) -> None:
        execution.delivery_blocked(
            "Send cancelled while worker may still write; outcome UNKNOWN, inspect the bus, do not retry",
            execution.submission.source_text,
        )

    def response_finished(self, execution: SubmissionExecution) -> None:
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

    def acknowledged_by(self, view: ConversationSubmissions) -> bool:
        return view.queue_source.contains_message(view, self.root, self.sent)

    async def present_written(self, execution: SubmissionExecution) -> None:
        if execution.current:
            await execution.present_message(self.sent)


@dataclass(frozen=True)
class SendBlocked(RetainedSend):
    description: str

    def presented(self, execution: SubmissionExecution, evidence: SendState) -> None:
        """A late original acknowledgement resolves the already-finished request."""
        execution.enter(NoSend())
        execution.owner.finish(execution)

    @property
    def reason(self) -> str:
        return f"Send blocked: {self.description}"


class SubmissionExecution(SubmissionStart, PromptSubmissionOutcome):
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
        self.owner.refresh_submission_state()

    def accepted(self, accepted: Container[InputId]) -> bool:
        return False

    def native_input_presented(self, started: InputStartedUpdate) -> None:
        """A non-native source has no native start to observe."""

    async def feedback(self):
        """Only a source's own acceptance can confirm its input."""

    async def present_message(self, sent: Message) -> None:
        """A native submission has no independently published BUS message to present."""

    async def prepare(self):
        view, submission = self.owner, self.submission
        self.owner.publish_pending()
        self.owner.record_history(view.input_histories.prompt, submission.source_text)
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

    def response_finished(self) -> None:
        self.state.response_finished(self)

    def response_confirmed(self) -> None:
        self.state.response_confirmed(self)

    def response_failed(self, failure: ACPFailure) -> None:
        self.state.response_failed(self, failure)

    def finish(self) -> None:
        self.response_finished()
        self.owner.finish(self)

    def delivery_blocked(self, description: str, body: str) -> None:
        self.enter(SendBlocked(description))
        if self.owner.is_attached:
            self.owner.prompt.restore_draft(body)
            self.owner.feedback.flash(self.state.reason, style="error")

    def delivery_refused(self, description: str, body: str) -> None:
        self.enter(NoSend())
        if self.owner.is_attached:
            self.owner.delivery_refused(description, body)


class MessageSubmissionExecution(SubmissionExecution):
    """An original Core publication, including a worker whose outcome is UNKNOWN."""

    def __init__(self, owner: ConversationSubmissions, submission: PromptInputSubmission,
                 root: Path, conversation: MessageDestination, current: Callable[[], bool],
                 present: Callable[[Message], Awaitable[None]]):
        super().__init__(owner, submission)
        self.root, self.conversation = root, conversation
        self.source_current, self._present = current, present
        self.publication: asyncio.Task[Message] | None = None

    @property
    def current(self) -> bool:
        return self.source_current()

    async def present_message(self, sent: Message) -> None:
        await self._present(sent)

    async def deliver(self):
        view, body = self.owner, self.submission.source_text
        try:
            comms = await view.app.coordination_access.transcripts.service(self.root)
            read_only = await view.app.preparation.run_thread(self.conversation.read_only, comms)
            if read_only:
                raise HumanSendRefusedError(RelationViolationError("Read-only saved view"))
            route_current = await view.app.preparation.run_thread(
                lambda: view.app.coordination_access.current(self.root))
            if not route_current or not self.current:
                raise HumanSendRefusedError(RelationViolationError("Message route changed; reopen this view"))
            runtime = view.app.preparation
            self.publication = await runtime.start_thread(partial(
                comms.messaging.send_user_message, self.conversation.send_target(), body,
                worktree=view.project_path))
            self.enter(SendPending())
            self.publication.add_done_callback(
                self.publication_finished, context=runtime.renderer.execution_context(),
            )
            try:
                await runtime.renderer.wait_for_work(self.publication)
            except asyncio.CancelledError:
                self.state.waiter_cancelled(self)
                return
        except asyncio.CancelledError:
            self.delivery_refused("Cancelled before sending", body)
            raise
        except (HumanSendError, RouteChangedError) as error:
            delivery_failure(error).present(self, body)
            return
        await self.state.present_written(self)

    def publication_finished(self, completed: asyncio.Task[Message]) -> None:
        """The original physical writer resolves UNKNOWN; no waiter may replay it."""
        try:
            sent = completed.result()
        except CommittedMessageError as error:
            sent = error.record
        except (HumanSendError, RouteChangedError) as error:
            view = self.owner
            view.log.error("Original message publication failed", self.root, error)
            delivery_failure(error).present(self, self.submission.source_text)
            self.owner.finish(self)
            return
        self.enter(SentAwaitingSource(self.root, sent))
        if self.current:
            self.owner.settle_acknowledged()


class ConversationSubmissions(QueueView, PromptTurnTarget, InputPresentation, DeliveryFailureView):
    """The view inherits its submission lifetime; each execution remains independent."""

    input_histories: InputHistories
    project_path: Checkout
    contents: HistoryNotifications
    transcript: TranscriptPresentation
    window: HistoryWindow

    @property
    @abstractmethod
    def queue_source(self) -> QueueSource: ...

    @property
    @abstractmethod
    def shell(self) -> ShellOperationalSource: ...

    @abstractmethod
    async def post_shell(self, command: str) -> None: ...

    @abstractmethod
    async def auto_name_from_prompt(self, prompt: str) -> None: ...

    @abstractmethod
    def jump_to_latest(self) -> None: ...

    @abstractmethod
    async def execute_command(self, text: str) -> bool: ...

    @abstractmethod
    def bind_bus_submission(
        self, source: BusSubmissionSource, submission: PromptInputSubmission,
    ) -> SubmissionStart: ...

    def initialize_submissions(self) -> None:
        self.pending_submissions: list[SubmissionExecution] = []

    @property
    def retains_surface(self) -> bool:
        """Pending, unacknowledged and UNKNOWN intent still owns this view's resources."""
        return bool(self.pending_submissions)

    async def close_submissions(self) -> None:
        workers = self.workers.cancel_group(self, SubmissionExecution.worker_group)
        # Worker reports errors itself; retirement waits for every completion,
        # including cancellation, before the view releases its draft resources.
        await asyncio.gather(*(worker.wait() for worker in workers), return_exceptions=True)

    def begin(self, submission: PromptInputSubmission):
        return self.queue_source.begin_submission(self, submission)

    def record_history(self, history: InputHistory, text: str) -> Worker[bool]:
        return self.run_worker(partial(history.record, text), group="history")

    def unbound(self, submission: PromptInputSubmission, refusal: InputRefused):
        return UnboundSubmissionStart(self, submission, refusal)

    def start(self, execution: SubmissionExecution):
        self.pending_submissions.append(execution)
        self.refresh_submission_state()
        return execution

    def start_message(self, submission: PromptInputSubmission, root: Path, conversation: MessageDestination,
                      current: Callable[[], bool], present: Callable[[Message], Awaitable[None]]):
        return self.start(MessageSubmissionExecution(self, submission, root, conversation, current, present))

    @property
    def send_block_reason(self) -> str:
        return next((item.state.reason for item in self.pending_submissions if item.state.reason), "")

    @property
    def input_decision(self) -> InputDecision:
        return self.queue_source.input_decision(self)

    async def submit(self, event: UserInputSubmitted):
        text = event.body.strip()
        if not event.shell and text.startswith("/") and await self.execute_command(text):
            return
        if self.send_block_reason:
            self.delivery_refused(self.send_block_reason, event.body)
            return
        return await InputSubmission.from_event(event, self).execute(self)

    @property
    def queue_evidence(self) -> QueueEvidence:
        return QueueEvidence(
            self.agent_binding.presentation, self.delivering,
            self.send_block_reason, self.contents.notification_targets,
            self.queue_source.capture_queue_service(self))

    @property
    def queue_summary(self) -> str:
        return self.queue_source.queue_summary(self.queue_evidence)

    @property
    def queue_projection(self):
        return self.agent_binding.presentation.queue

    @property
    def queued_inputs(self):
        """Accepted producer rows not yet handed to their original native body."""
        return self.queue_projection.items

    @property
    def delivering(self):
        queue = self.queue_projection
        accepted = {row.input_id for row in (*queue.items, *queue.restored)}
        return tuple(text for item in self.pending_submissions if item.current
                     for text in item.state.local_intent(item, accepted))

    def native_input_presented(self, started: InputStartedUpdate):
        """Retain this request's actual response while its RPC is outstanding."""
        for execution in self.pending_submissions:
            execution.native_input_presented(started)

    def publish_pending(self):
        self.queue_evidence_changed()

    def retire(self, execution: SubmissionExecution) -> None:
        if execution in self.pending_submissions:
            self.pending_submissions.remove(execution)

    def finish(self, execution: SubmissionExecution):
        execution.state.settle(execution)
        self.publish_pending()

    def settle_acknowledged(self) -> None:
        for execution in tuple(self.pending_submissions):
            if execution.state.acknowledged_by(self):
                execution.enter(NoSend())
                self.finish(execution)

    def send_now(self):
        source = self.queue_source
        evidence = self.queue_evidence
        return self.run_worker(
            partial(self._send_now, source, evidence, source.queue_scope(evidence)),
            group="send-queued-now", exclusive=True,
        )

    async def _send_now(self, source: QueueActions, evidence: QueueEvidence, scope: QueueScope) -> None:
        try:
            await source.queue_send_now(evidence, scope)
        except (RequestError, QueueActionRefused) as error:
            self.feedback.flash(f"Send now failed: {error}", style="error")
        self.publish_pending()


class QueueSource(QueueActions):
    """The captured source controls sending, observation and queue changes."""

    preview_limit: ClassVar[int] = 3

    def capture_queue_service(self, view: QueueView) -> Callable[[], Comms]:
        return view.queue_observation_service

    def send_now_available(self, owner: ConversationSubmissions) -> bool:
        return self.queue_actions_available(owner.queue_evidence)

    def begin_submission(self, owner: ConversationSubmissions,
                         submission: PromptInputSubmission) -> SubmissionStart:
        return owner.unbound(submission, InputSourceUnavailable())

    def input_decision(self, view: QueueView) -> InputDecision:
        return InputSourceUnavailable()

    def defers_input(self, view: QueueView) -> bool:
        return False

    def contains_message(self, view: QueueView, root: Path, sent: Message) -> bool:
        """Only the original message source can confirm its committed row."""
        return False

    def queue_summary(self, evidence: QueueEvidence) -> str:
        local = evidence.delivering
        submitting = (f"Submitting ({len(local)}): " + " · ".join(
            QueueItem.summarize(text) for text in local[:self.preview_limit])) if local else ""
        return " | ".join(part for part in (
            evidence.transport, submitting, self.observed_summary(evidence)) if part)

    def observed_summary(self, evidence: QueueEvidence) -> str:
        return "Queue unavailable"

    def queue_details(self, evidence: QueueEvidence) -> DetailLines:
        lines: list[tuple[Span, ...]] = [(Span("Submitting is local intent; acceptance is not consumption.", MutedRole),)]
        lines.extend((Span(f"Submitting: {QueueItem.summarize(text)}", MutedRole),)
                     for text in evidence.delivering)
        if evidence.transport:
            lines.append((Span(evidence.transport, MutedRole),))
        lines.extend(self.observed_details(evidence))
        return tuple(lines)

    def observed_details(self, evidence: QueueEvidence) -> DetailLines:
        return ((Span("No queue observation is available for this source.", MutedRole),),)
