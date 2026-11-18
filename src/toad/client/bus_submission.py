"""A message typed into a bus conversation, from the composer to Core and back: the view's
pending sends, their order, what each still shows as submitting, and how a refusal or an
unknown outcome reaches the owner. No toolkit: Textual's and Qt's conversation views
each answer SubmissionView, and both send through BusSubmissions."""

from __future__ import annotations


import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.acp_extension import InputStartedUpdate, QueueItem
from formbridge.operations import OperationKind
from agent_comms.errors import (
    CommittedMessageError,
    HumanSendError,
    HumanSendRefusedError,
    RelationViolationError,
    RouteChangedError,
)
from agent_comms.messaging.delivery_failure import delivery_failure
from agent_comms.messaging.message_files import FileUpload
from agent_comms.messaging.message_reference import MessageReference

from toad.client.application import ClientApplication
from toad.client.connection import Observing
from toad.client.input_decision import InputAccepted, InputDecision, InputRefused
from toad.client.line_blocks import MutedRole, Span
from toad.client.notification_status import DetailLines
from toad.client.prompt_composer import PromptComposer
from toad.client.submission import (
    BusDestination,
    ComposeAccess,
    MessageDestination,
    SubmissionOwner,
    SubmissionStart,
    SubmittedText,
)


class ConversationSubmission(OperationKind):
    """One message's send from a conversation view; sends run side by side and are never
    superseded. Textual runs it as the view's worker group, Qt as the app's operation."""


class SubmissionView:
    """What a submission asks of the view it was typed in. Each toolkit's conversation view
    answers it; the shared submissions never touch a widget."""

    app: ClientApplication

    @staticmethod
    def refusal_notice(description: str) -> str:
        return f"Send failed: {description}"

    @staticmethod
    def unknown_notice(description: str) -> str:
        return f"Send outcome unknown: {description}. Check this conversation before resending."

    @property
    @abstractmethod
    def submission_composer(self) -> PromptComposer:
        """The composer a returned draft goes back into."""

    @abstractmethod
    def show_send_failure(self, text: str) -> None:
        """Say why a send came back, where this view says what went wrong."""

    def delivery_refused(self, description: str, draft: SubmittedText) -> None:
        """Nothing left this machine, or Core refused it: the draft comes back with why."""
        self.submission_composer.restore(draft)
        self.show_send_failure(self.refusal_notice(description))

    def delivery_unknown(self, description: str, draft: SubmittedText) -> None:
        """The request may have reached Core; the draft comes back with a warning."""
        self.submission_composer.restore(draft)
        self.show_send_failure(self.unknown_notice(description))

    @abstractmethod
    async def refresh_composer(self, access: ComposeAccess) -> None:
        """Draw compose from the caller's Core answer: held or open, and whether it offers
        files."""

    @abstractmethod
    def draws_user_message(self, reference: MessageReference) -> bool: ...

    @abstractmethod
    def record_input(self, text: str) -> None:
        """Keep the submitted text in the composer's input history."""

    @abstractmethod
    def run_submission(self, send: Callable[[], Awaitable[None]]) -> object:
        """Run one request's send as the view's background work; its failure reaches the
        native failure owner."""

    @abstractmethod
    def submissions_changed(self) -> None:
        """The pending sends changed: the composer redraws what is submitting."""


@dataclass(frozen=True)
class TypedText(SubmittedText):
    """Text typed into a message composer, exactly as typed, and the files attached to it."""

    source_text: str
    files: tuple[FileUpload, ...]


@dataclass(frozen=True)
class SubmittingTexts:
    """The view's own requests its destinations have not taken yet, as the composer lists them."""

    texts: tuple[str, ...]
    preview_limit: ClassVar[int] = 3

    @property
    def summary(self) -> tuple[str, ...]:
        texts = tuple(QueueItem.summarize(text) for text in self.texts)
        return (f"Submitting ({len(texts)}): " + " · ".join(texts[:self.preview_limit]),) if texts else ()

    @property
    def details(self) -> DetailLines:
        return tuple((Span(f"Submitting: {QueueItem.summarize(text)}", MutedRole),) for text in self.texts)

    @staticmethod
    def held_hint(count: int) -> str:
        """The one-word stand-in for the delivery preview while it is off: how many of the
        view's messages are still held, and nothing when none is."""
        return f"⧗ {count} held" if count else ""


class UnboundSubmissionStart(SubmissionStart):
    def __init__(self, owner: BusSubmissions, submission: SubmittedText, refusal: InputRefused):
        self.owner, self.submission, self.refusal = owner, submission, refusal

    async def prepare(self):
        self.owner.view.delivery_refused(self.refusal.message, self.submission)


class SubmissionExecution(SubmissionStart):
    """One outstanding local request: shown above the composer until its destination has it,
    while the composer stays open. Members differ only in where the text goes."""

    def __init__(self, owner: BusSubmissions, submission: SubmittedText):
        self.owner, self.submission = owner, submission

    async def prepare(self):
        owner, submission = self.owner, self.submission
        view = owner.view
        owner.publish_pending()
        view.record_input(submission.source_text)
        try:
            await self.present()
            if self.current:
                return view.run_submission(self.send)
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

    def previewed(self) -> tuple[str, ...]:
        """The text the delivery preview lists for this request: what is still submitting."""
        return self.delivering()

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

    def previewed(self, text: str) -> tuple[str, ...]:
        """What the delivery preview lists for this submission: what is still submitting.
        A phase whose message is neither submitting nor drawn yet keeps it listed."""
        return self.submitting(text)


class BusOutcome(SubmittingPhase):
    """Where a bus send stands: only a sent message can be drawn by its view."""

    def drawn_by(self, view: SubmissionView) -> bool:
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

    def drawn_by(self, view: SubmissionView) -> bool:
        return view.draws_user_message(self.reference)

    def previewed(self, text: str) -> tuple[str, ...]:
        """Core has it and the history has not drawn it yet: the preview keeps it until the
        execution settles on the draw, so a sent message is on screen at every instant (it
        dropped out on Core's answer and showed nowhere until the history drew it — Tristan,
        2026-11-18: "there's a gap where I don't see the queue and I don't see the message")."""
        return (text,)

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

    def __init__(self, owner: BusSubmissions, submission: SubmittedText,
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

    def previewed(self) -> tuple[str, ...]:
        return self.outcome.previewed(self.submission.text) if self.current else ()

    def retire_unsent(self) -> None:
        """A message to a view that changed before it left comes back as the draft."""
        self.owner.view.delivery_refused("Message route changed; reopen this view", self.submission)
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
        view, draft, destination = self.owner.view, self.submission, self.destination
        access, preparation = view.app.coordination_access, view.app.preparation
        try:
            await self.after.wait()
            observed = await preparation.run_thread(access.observing, destination.root)
            compose = await preparation.run_thread(destination.conversation.compose_access, observed.core)
            await view.refresh_composer(compose)
            if compose.read_only:
                view.delivery_refused(MessageDestination.read_only_reason, draft)
                return RefusedMessage()
            if compose.refuses(draft):
                view.delivery_refused(compose.files_refused_reason, draft)
                return RefusedMessage()
            route_current = await preparation.run_thread(lambda: access.current(destination.root))
            if not route_current or not self.current:
                raise HumanSendRefusedError(RelationViolationError("Message route changed; reopen this view"))
        except asyncio.CancelledError:
            view.delivery_refused("Cancelled before sending", draft)
            raise
        except (HumanSendError, RouteChangedError) as error:
            view.delivery_refused(delivery_failure(error).description, draft)
            return RefusedMessage()
        except Exception:
            # Nothing left this machine: the draft comes back, and the failure stays loud.
            view.delivery_refused("the send failed before it left this machine", draft)
            raise
        try:
            return await self.commit(observed, draft)
        except (HumanSendError, RouteChangedError) as error:
            view.delivery_refused(delivery_failure(error).description, draft)
            return RefusedMessage()

    async def commit(self, observed: Observing, draft: SubmittedText) -> DeliveryOutcome:
        view = self.owner.view
        task = asyncio.create_task(asyncio.to_thread(
            observed.send_user_message, self.destination.conversation.send_target(), draft.source_text,
            draft.files))
        try:
            return SentMessage(await asyncio.shield(task))
        except asyncio.CancelledError:
            view.delivery_unknown("the send was cancelled while it may still be writing", draft)
            def _surface_late_exc(done: asyncio.Future) -> None:
                if done.cancelled():
                    return
                exc = done.exception()
                if exc is None:
                    return
                # The outer await was cancelled; the inner task kept running and raised.
                # Nothing is listening for this exception any more, but it is real and the
                # silent-swallow pattern (PR #2013 ModuleNotFoundError) is what we're
                # ruling out: traceback to stderr so logcat / dev tooling sees it.
                import traceback
                traceback.print_exception(type(exc), exc, exc.__traceback__)
            task.add_done_callback(_surface_late_exc)
            return RefusedMessage()
        except CommittedMessageError as error:
            return SentMessage(error.record.reference)
        except (HumanSendError, RouteChangedError):
            raise
        except Exception:
            # The request left: Core may have published it. Raise for the log, never hold compose.
            view.delivery_unknown("its reply could not be read", draft)
            raise


class BusSubmissions(SubmissionOwner):
    """A view's pending local sends: each bus message queues behind the earlier ones and
    shows as submitting until the view draws it. An agent conversation adds its prompts."""

    # ConversationSubmissions overrides this as a property that reads the agent's live
    # queue state; bus-only submissions have no queue to project. Declaring None on the
    # base means consumers (e.g. QtQueueUi) can read the attribute directly.
    queue_evidence: ClassVar[object | None] = None

    def __init__(self, view: SubmissionView):
        self.view = view
        self.active: list[SubmissionExecution] = []
        self.bus_order = asyncio.Event()
        self.bus_order.set()

    def unbound(self, submission: SubmittedText, refusal: InputRefused):
        return UnboundSubmissionStart(self, submission, refusal)

    def start_bus(self, submission: SubmittedText, destination: BusDestination):
        """Queue a bus message behind this view's earlier ones; the composer stays open."""
        execution = BusSubmissionExecution(self, submission, destination, self.bus_order)
        self.bus_order = execution.accepted
        self.active.append(execution)
        return execution

    @property
    def delivering(self) -> tuple[str, ...]:
        return tuple(text for execution in self.active for text in execution.delivering())

    @property
    def previewed(self) -> tuple[str, ...]:
        """What the delivery preview lists: every request until the view draws it. Send now
        reads `delivering` instead, since a message Core has cannot be sent again."""
        return tuple(text for execution in self.active for text in execution.previewed())

    @property
    def submitting(self) -> SubmittingTexts:
        return SubmittingTexts(self.previewed)

    @property
    def input_decision(self) -> InputDecision:
        """A message composer always takes input; a read-only view holds compose instead."""
        return InputAccepted()

    @property
    def holds_input(self) -> bool:
        """A message still submitting can be sent now."""
        return bool(self.delivering)

    @property
    def queue_summary(self) -> str:
        return " | ".join(self.submitting.summary)

    @property
    def queue_hint(self) -> str:
        return self.submitting.held_hint(len(self.submitting.texts))

    def settle(self) -> None:
        """The view drew new messages: retire the bus sends they show."""
        for execution in tuple(self.active):
            execution.settle()

    def publish_pending(self):
        self.view.submissions_changed()

    def finish(self, execution: SubmissionExecution):
        if execution in self.active:
            self.active.remove(execution)
        if execution.current:
            self.publish_pending()

    def reset(self):
        self.active.clear()
        self.publish_pending()
