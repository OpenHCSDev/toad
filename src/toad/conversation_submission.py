"""One submission transaction owns input intent, request identity and draft recovery."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import ClassVar

from acp.exceptions import RequestError
from agent_comms.delivery_failure import delivery_failure
from agent_comms.errors import (
    CommittedMessageError,
    HumanSendError,
    HumanSendRefusedError,
    RelationViolationError,
    RouteChangedError,
)
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.acp_extension import (
    InputStartedUpdate,
    PendingQueueProjection,
    QueuePromptRequest,
    QueueScope,
    SteerPromptRequest,
)
from agent_comms.nominal.declared_family import DeclaredFamily

from toad import messages
from toad.delivery_failure_view import DeliveryFailureView
from toad.bus_submission import (
    BusDestination,
    SubmissionOwner,
    SubmissionStart,
    SubmittedText,
)
from toad.acp.client_session import ClientSessionRequest
from toad.command_catalog import CommandCatalog
from toad.acp.agent import Agent
from toad.acp.status import StopReason, UnreportedStopReason
from toad.comms_root import Observing
from toad.acp.queue_attachment import QueueActionRefused
from toad.submission_queue import QueueEvidence, QueueSource
from toad.core.input_events import UserInputSubmitted
from toad.core_event_carrier import CoreEventMessage
from toad.input_decision import InputDecision, InputRefused
from toad.widgets.prompt import Prompt
from toad.worker_group import InputHistoryRecord

@dataclass(frozen=True)
class InputSubmission(SubmittedText, DeclaredFamily, affix="InputSubmission"):
    source_text: str
    priority: ClassVar[int] = 0

    @classmethod
    @abstractmethod
    def matches(cls, event: UserInputSubmitted, owner: ConversationSubmissions): ...

    @abstractmethod
    async def execute(self, owner: ConversationSubmissions): ...

    @classmethod
    def from_event(cls, event: UserInputSubmitted, owner: ConversationSubmissions):
        kind = next(
            kind
            for kind in sorted(cls.members_with(InputSubmission), key=lambda kind: kind.priority, reverse=True)
            if kind.matches(event, owner)
        )
        return kind(event.body)


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


class UnboundSubmissionStart(SubmissionStart):
    def __init__(
        self, owner: ConversationSubmissions, submission: SubmittedText, refusal: InputRefused
    ):
        self.owner, self.submission, self.refusal = owner, submission, refusal

    async def prepare(self):
        self.owner.view.delivery_refused(
            self.refusal.message,
            self.submission.source_text,
        )


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
        view = owner.view
        return await owner.begin(self).prepare()


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


class SubmissionExecution(SubmissionStart):
    """One outstanding local request: shown above the composer until its destination has it,
    while the composer stays open. Members differ only in where the text goes."""

    def __init__(self, owner: ConversationSubmissions, submission: SubmittedText):
        self.owner, self.submission = owner, submission

    async def prepare(self):
        owner, submission = self.owner, self.submission
        view = owner.view
        owner.publish_pending()
        InputHistoryRecord.run_on(view, partial(view.input_histories.prompt.record, submission.source_text))
        try:
            await self.present()
            if self.current:
                return view.run_worker(partial(self.send), group="conversation-submission")
            self.retire_unsent()
        except BaseException:
            owner.finish(self)
            raise

    async def present(self) -> None:
        """What the view shows before the request leaves; nothing by default."""

    def retire_unsent(self) -> None:
        """The destination went away before the request left; an agent prompt just retires."""
        self.owner.finish(self)

    @property
    @abstractmethod
    def current(self) -> bool: ...

    @property
    def retired(self):
        return not self.current

    @abstractmethod
    async def send(self) -> None: ...

    @abstractmethod
    def delivering(self) -> tuple[str, ...]:
        """The text this request still shows as submitting, or nothing once its destination has it."""

    def settle(self) -> None:
        """A drawn message retires the requests it satisfies; an agent prompt is retired by its RPC."""

    def input_presented(self, started: InputStartedUpdate) -> None:
        """A native input start answers only the agent prompt that requested it."""


class SubmittingPhase(ABC):
    """Whether a submission still shows as submitting: its destination has not taken it yet.

    Both kinds of destination answer this, so both kinds of execution read their own
    phase for it instead of each deciding again from whatever is in reach.
    """

    @abstractmethod
    def submitting(self, text: str) -> tuple[str, ...]: ...


class PromptPhase(SubmittingPhase):
    """Whether the agent has started this prompt: until it does, the prompt still shows as submitting."""


class PromptUnstarted(PromptPhase):
    def submitting(self, text: str) -> tuple[str, ...]:
        return (text,)


class PromptStarted(PromptPhase):
    def submitting(self, text: str) -> tuple[str, ...]:
        return ()


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


class BusOutcome(SubmittingPhase):
    """Where a bus send stands: only a sent message can be drawn by its view."""

    def drawn_by(self, view: DeliveryFailureView) -> bool:
        return False


class NotYetSent(BusOutcome):
    """Still queued or on its way to Core."""

    def submitting(self, text: str) -> tuple[str, ...]:
        return (text,)


class DeliveryOutcome(BusOutcome):
    """What Core's answer leaves the execution to do."""

    def submitting(self, text: str) -> tuple[str, ...]:
        """Core answered, so nothing is being submitted: the entry that stays is waiting
        to be drawn, which is not the same thing as a message still on its way."""
        return ()

    @abstractmethod
    async def settle_into(self, execution: BusSubmissionExecution) -> None: ...


@dataclass(frozen=True)
class SentMessage(DeliveryOutcome):
    """Core has the message; the entry stays until the view draws it."""

    reference: MessageReference

    def drawn_by(self, view: DeliveryFailureView) -> bool:
        return view.draws_user_message(self.reference)

    async def settle_into(self, execution: BusSubmissionExecution) -> None:
        execution.outcome = self
        execution.owner.publish_pending()
        await execution.destination.presented(self.reference)
        execution.settle()


class RefusedMessage(DeliveryOutcome):
    """Refused, or its fate already answered to the user; the entry just goes."""

    async def settle_into(self, execution: BusSubmissionExecution) -> None:
        execution.owner.finish(execution)


class BusSubmissionExecution(SubmissionExecution):
    """A human message to the bus. It queues behind the view's earlier messages, so they reach
    Core in the order they were typed, and shows as submitting until the view draws it."""

    def __init__(self, owner: ConversationSubmissions, submission: SubmittedText,
                 destination: BusDestination, after: asyncio.Event):
        super().__init__(owner, submission)
        self.destination, self.after = destination, after
        self.accepted = asyncio.Event()
        self.outcome: BusOutcome = NotYetSent()

    @property
    def current(self):
        return self.destination.shown()

    def delivering(self) -> tuple[str, ...]:
        """The outcome owns whether this is still submitting; `current` only says the
        destination is still shown, which is a different question."""
        return self.outcome.submitting(self.submission.text) if self.current else ()

    def retire_unsent(self) -> None:
        """A message to a view that changed before it left comes back as the draft."""
        self.owner.view.delivery_refused("Message route changed; reopen this view", self.submission.source_text)
        self.owner.finish(self)

    def settle(self) -> None:
        if self.outcome.drawn_by(self.owner.view):
            self.owner.finish(self)

    async def send(self):
        try:
            outcome = await self.deliver()
        except BaseException:
            self.owner.finish(self)
            raise
        finally:
            self.accepted.set()
        await outcome.settle_into(self)

    async def deliver(self) -> DeliveryOutcome:
        """Send after the earlier messages; a refusal is answered here."""
        view, body, destination = self.owner.view, self.submission.source_text, self.destination
        access = view.app.coordination_access
        try:
            await self.after.wait()
            observed = await view.app.preparation.run_thread(access.observing, destination.root)
            read_only = await view.app.preparation.run_thread(destination.conversation.read_only, observed.core)
            await view.refresh_composer(read_only)
            if read_only:
                view.delivery_refused(f"{view.status}", body)
                return RefusedMessage()
            route_current = await view.app.preparation.run_thread(lambda: access.current(destination.root))
            if not route_current or not self.current:
                raise HumanSendRefusedError(RelationViolationError("Message route changed; reopen this view"))
        except asyncio.CancelledError:
            view.delivery_refused("Cancelled before sending", body)
            raise
        except (HumanSendError, RouteChangedError) as error:
            delivery_failure(error).present(view, body)
            return RefusedMessage()
        except Exception:
            # Nothing left this machine: the draft comes back, and the failure stays loud.
            view.delivery_refused("the send failed before it left this machine", body)
            raise
        try:
            return await self.commit(observed, body)
        except (HumanSendError, RouteChangedError) as error:
            delivery_failure(error).present(view, body)
            return RefusedMessage()

    async def commit(self, observed: Observing, body: str) -> DeliveryOutcome:
        view = self.owner.view
        task = asyncio.create_task(asyncio.to_thread(
            observed.send_user_message, self.destination.conversation.send_target(), body))
        try:
            return SentMessage(await asyncio.shield(task))
        except asyncio.CancelledError:
            view.delivery_unknown("the send was cancelled while it may still be writing", body)
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
            return RefusedMessage()
        except CommittedMessageError as error:
            return SentMessage(error.record.reference)
        except (HumanSendError, RouteChangedError):
            raise
        except Exception:
            # The request left: Core may have published it. Raise for the log, never hold compose.
            view.delivery_unknown("its reply could not be read", body)
            raise


class ConversationSubmissions(SubmissionOwner):
    """Own pending local transactions; remote membership stays with QueueAttachment."""

    def __init__(self, view):
        self.view = view
        self.active: list[SubmissionExecution] = []
        self.bus_order = asyncio.Event()
        self.bus_order.set()

    def begin(self, submission: AgentInputSubmission):
        return self.view.begin_submission(self, submission)

    def unbound(self, submission: SubmittedText, refusal: InputRefused):
        return UnboundSubmissionStart(self, submission, refusal)

    def start(self, submission: AgentInputSubmission, agent: Agent):
        execution = AgentSubmissionExecution(self, submission, agent)
        self.active.append(execution)
        return execution

    def start_bus(self, submission: SubmittedText, destination: BusDestination):
        """Queue a bus message behind this view's earlier ones; the composer stays open."""
        execution = BusSubmissionExecution(self, submission, destination, self.bus_order)
        self.bus_order = execution.accepted
        self.active.append(execution)
        return execution

    @property
    def input_decision(self) -> InputDecision:
        return self.view.operational_sources.input_decision(self.view)

    async def submit(self, event: UserInputSubmitted):
        text = event.body.strip()
        if not event.shell and text.startswith("/") and await CommandCatalog.execute(text, self.view):
            return
        return await InputSubmission.from_event(event, self).execute(self)

    def accepts_failure(self, message: CoreEventMessage):
        return self.view.agent_binding.accepts_failed_input(message)

    @property
    def queue_evidence(self) -> QueueEvidence:
        return QueueEvidence(
            self.view.agent_binding.presentation, self.delivering, self.view.turns.owner.busy,
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
    def queue_projection(self):
        return self.view.agent_binding.presentation.queue

    @property
    def queued_inputs(self):
        """Accepted producer rows not yet handed to their original native body."""
        return self.queue_projection.items

    @property
    def delivering(self):
        return tuple(text for execution in self.active for text in execution.delivering())

    def settle(self) -> None:
        """The view drew new messages: retire the bus sends they show."""
        for execution in tuple(self.active):
            execution.settle()

    def native_input_presented(self, started: InputStartedUpdate):
        """Retain this request's actual response while its RPC is outstanding."""
        for execution in self.active:
            execution.input_presented(started)

    def publish_pending(self):
        if (prompt := self.view.query_one_optional(Prompt)) is not None:
            prompt.sync_queue()

    def finish(self, execution: SubmissionExecution):
        if execution in self.active:
            self.active.remove(execution)
        if execution.current:
            self.publish_pending()

    def reset(self):
        self.active.clear()
        self.publish_pending()

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
