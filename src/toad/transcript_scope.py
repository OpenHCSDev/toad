"""A transcript address: the reads, observations, mailbox sends and absent behavior of one
thread birth, or of no thread."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Never

from agent_comms.messaging.channel_targets import ThreadTarget
from agent_comms.coordination.errors import CoordinationReadUnavailable, ReadAgain
from agent_comms.errors import RouteChangedError
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.registry.thread_presentation import ThreadPresentation
from agent_comms.transport.tools.reads import TranscriptPageRead
from agent_comms.ui_model.observation import ReadTranscript, ReadTranscriptUpdate, TranscriptPublicationState
from rich.text import Text as RichText
from textual.content import Content

from agent_comms.transcripts import AtFrontier, LatestPage, LivePageSource, PageLimit, PagePosition, PageSource

from toad.app_node import ToadNode
from toad.bus_submission import BusDestination, SubmissionOwner, SubmissionStart, SubmittedText
from toad.comms_root import CoordinationAccess, Observing
from toad.conversation_kind import DmConversation
from toad.core.events import ThreadRowsChanged
from toad.core_event_carrier import CoreEventReceiver, ThreadCallbackSubscription
from toad.input_decision import InputAccepted, InputDecision, TranscriptNotReady
from toad.owner_preparation import ExistingOwnerPlan
from toad.resource_release import ResourceRelease
from toad.status_thread import NoStatusThread, StatusThread
from agent_comms.nominal.field_codec import AcpSessionId


class TranscriptView(CoreEventReceiver, ToadNode):
    """A view that shows one transcript scope: its scope observes core events through it and
    gives its thread status to it."""

    thread_status: str | Content | RichText

    @property
    @abstractmethod
    def thread_scope(self) -> TranscriptScope:
        """The transcript scope this view is bound to now."""

    @abstractmethod
    def follow_latest(self) -> None:
        """Show the transcript's end."""

    @abstractmethod
    def transcript_changed(self) -> None:
        """The transcript's source changed outside this view: read it again."""


class MailboxSent(ABC):
    """What a CLI thread's sources do once its inbox message is delivered."""

    @abstractmethod
    async def mailbox_sent(self, view: TranscriptView, sent: MessageReference) -> None: ...


@dataclass(frozen=True)
class MailboxDestination(BusDestination):
    """A CLI thread's inbox: shown while its view stays bound to this transcript."""

    scope: KnownTranscript
    view: TranscriptView
    sources: MailboxSent

    def shown(self) -> bool:
        return self.scope.shown_by(self.view)

    async def presented(self, sent: MessageReference) -> None:
        await self.sources.mailbox_sent(self.view, sent)


class TranscriptScope(ABC):
    """A transcript address owns its reads, observations and absent behavior."""

    @property
    @abstractmethod
    def readable(self) -> bool: ...

    @abstractmethod
    def owner_decision(self, presentation: ThreadPresentation) -> InputDecision: ...

    @abstractmethod
    def original_threads(self) -> tuple[tuple[str, ThreadIncarnation], ...]: ...

    @abstractmethod
    def matches_session(self, access: CoordinationAccess, session_id: AcpSessionId) -> bool: ...

    @abstractmethod
    def status_thread(self, access: CoordinationAccess) -> StatusThread: ...

    @abstractmethod
    def observe(
        self,
        view: TranscriptView,
        access: CoordinationAccess,
        resume: Callable[[ThreadRowsChanged], object],
    ) -> ResourceRelease: ...

    @abstractmethod
    def snapshot_request(
        self,
        *,
        position: PagePosition = LatestPage(),
        limit: PageLimit = AtFrontier(),
        page_source: PageSource = LivePageSource(),
    ) -> ReadTranscript: ...

    @abstractmethod
    def update_request(
        self,
        previous: TranscriptPublicationState,
        *,
        position: PagePosition = LatestPage(),
    ) -> ReadTranscriptUpdate: ...

    def queue_observing(self, observing: Callable[[], Observing]) -> Observing:
        raise RouteChangedError("The queue has no original transcript source")

    @abstractmethod
    def mailbox_target(self) -> ThreadTarget: ...

    @abstractmethod
    def begin_mailbox(
        self,
        owner: SubmissionOwner,
        submission: SubmittedText,
        view: TranscriptView,
        sources: MailboxSent,
    ) -> SubmissionStart: ...

    @abstractmethod
    async def show_mailbox_status(
        self, view: TranscriptView
    ) -> None: ...


@dataclass(frozen=True)
class KnownTranscript(TranscriptScope):
    """A transcript of one thread birth: a redeclared thread with the same name is another scope."""

    root: str
    incarnation: ThreadIncarnation
    readable = True

    @property
    def name(self) -> str:
        return self.incarnation.name

    def queue_observing(self, observing: Callable[[], Observing]) -> Observing:
        observed = observing()
        if observed.root != Path(self.root):
            raise RouteChangedError("The queue's original transcript root changed")
        return observed

    def owner_decision(self, presentation: ThreadPresentation) -> InputDecision:
        return ExistingOwnerPlan.from_binding(presentation.binding).decision

    def original_threads(self) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ((self.root, self.incarnation),)

    def matches_session(self, access: CoordinationAccess, session_id: AcpSessionId) -> bool:
        registry = access.observing(self.root).registry_for(session_id, self.name)
        return registry.canonical_name(session_id) == registry.require(self.name).name

    def status_thread(self, access: CoordinationAccess) -> StatusThread:
        return StatusThread.for_root(Path(self.root), self.name, access)

    def observe(
        self,
        view: TranscriptView,
        access: CoordinationAccess,
        resume: Callable[[ThreadRowsChanged], object],
    ) -> ResourceRelease:
        release = ResourceRelease()
        release.callback(
            view.retire_core,
            view.observe_core_callback(
                access.events,
                ThreadRowsChanged,
                resume,
                factory=partial(
                    ThreadCallbackSubscription, scope=(self.root, self.name)
                ),
            ),
        )
        return release

    def snapshot_request(
        self,
        *,
        position: PagePosition = LatestPage(),
        limit: PageLimit = AtFrontier(),
        page_source: PageSource = LivePageSource(),
    ) -> ReadTranscript:
        return ReadTranscript(self.root, TranscriptPageRead(
            thread=self.name,
            position=position,
            limit=limit,
            page_source=page_source,
        ))

    def update_request(
        self,
        previous: TranscriptPublicationState,
        *,
        position: PagePosition = LatestPage(),
    ) -> ReadTranscriptUpdate:
        return ReadTranscriptUpdate(
            self.root, TranscriptPageRead(thread=self.name, position=position), previous=previous
        )

    def mailbox_target(self) -> ThreadTarget:
        return ThreadTarget(self.name)

    def begin_mailbox(
        self,
        owner: SubmissionOwner,
        submission: SubmittedText,
        view: TranscriptView,
        sources: MailboxSent,
    ) -> SubmissionStart:
        return owner.start_bus(submission, MailboxDestination(
            self.root, self.mailbox_conversation(), self, view, sources))

    async def show_mailbox_status(
        self, view: TranscriptView
    ) -> None:
        """A CLI thread shows the same Core configuration answer a DM shows."""
        try:
            observed = await view.app.preparation.run_thread(view.app.coordination_access.observing, self.root)
            status = await self.mailbox_conversation().status_text(
                observed, read_only=False
            )
        except (CoordinationReadUnavailable, ReadAgain):
            # The next observed presentation reads the answer again.
            return
        if self.shown_by(view):
            view.thread_status = status

    def shown_by(self, view: TranscriptView) -> bool:
        """This transcript is still the one the view is bound to."""
        return view.is_attached and view.thread_scope == self

    def mailbox_conversation(self) -> DmConversation:
        return DmConversation(self.incarnation)


@dataclass(frozen=True)
class NoTranscript(TranscriptScope):
    readable = False

    def owner_decision(self, presentation: ThreadPresentation) -> InputDecision:
        return InputAccepted()

    def original_threads(self) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ()

    def matches_session(self, access: CoordinationAccess, session_id: AcpSessionId) -> bool:
        return False

    def status_thread(self, access: CoordinationAccess) -> StatusThread:
        return NoStatusThread()

    def observe(
        self,
        view: TranscriptView,
        access: CoordinationAccess,
        resume: Callable[[ThreadRowsChanged], object],
    ) -> ResourceRelease:
        return ResourceRelease()

    def unavailable(self) -> Never:
        raise ValueError("Transcript paging requires a bound thread")

    def snapshot_request(
        self,
        *,
        position: PagePosition = LatestPage(),
        limit: PageLimit = AtFrontier(),
        page_source: PageSource = LivePageSource(),
    ) -> Never:
        self.unavailable()

    def update_request(
        self,
        previous: TranscriptPublicationState,
        *,
        position: PagePosition = LatestPage(),
    ) -> Never:
        self.unavailable()

    def mailbox_target(self) -> Never:
        self.unavailable()

    def begin_mailbox(
        self,
        owner: SubmissionOwner,
        submission: SubmittedText,
        view: TranscriptView,
        sources: MailboxSent,
    ) -> SubmissionStart:
        return owner.unbound(submission, TranscriptNotReady())

    async def show_mailbox_status(
        self, view: TranscriptView
    ) -> None:
        """No bound thread has no configuration to show."""
