"""A channel or direct conversation's history as every frontend reads it: which painted messages
wait to be marked read, and the acknowledgement that marks them."""
import asyncio
from collections.abc import Callable
from functools import partial
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import ClassVar

from agent_comms.coordination.errors import ReadAgain
from agent_comms.messaging.historical_views import (
    ConversationObservation,
    ConversationRevision,
    UnobservedConversation,
)
from agent_comms.messaging.message_page import MessagePage, MessagePageRequest
from agent_comms.messaging.message_reference import MessageReference

from agent_comms.messaging.messages import Message
from agent_comms.messaging.notification_reads import LiveNotificationRead
from agent_comms.messaging.page_traversal import (
    LiveCursor,
    NewerTraversal,
    OlderTraversal,
    PageCursor,
)
from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import (
    CommsConversationRevisionTool,
    CommsLatestSequenceTool,
    CommsMarkPageReadTool,
)
from agent_comms.ui_model.observation import ReadNotifications
from toad.client.connection import CoordinationAccess, Observation
from toad.client.conversation import ConversationKind
from toad.client.conversation_capabilities import (
    ConversationActivity,
    ConversationSource,
)

from toad.client.fragments import EvidencedFragment, FragmentKey, MessageShown
from toad.client.history_preparation import HistorySourceSnapshot, PageRequest
from toad.client.history_reads import NothingToRead, PaintedRead, ReadMarking, ReadWork
from toad.client.message_file_links import PageFiles
from toad.client.history_state import (
    LatestReplacementViewportRequest,
    ReplacementViewportRequest,
)
from toad.client.prepared_pages import (
    PreparedTranscriptPage,
    ReplaceablePageSource,
    SavedHistory,
    SourceObservation,
    SourcePageWork,
    Unchanged,
)
from toad.client.reader_position import LatestPosition
from toad.client.source_resumption import ResumesSource
from toad.client.submission import (
    BusDestination,
    ComposeAccess,
    SubmissionOwner,
    SubmissionStart,
    SubmittedText,
)
from toad.message_rows import MessageRow, WireMessageStyle
from toad.submission_queue import BusQueueSource
from toad.target_commands import TargetContext


class ReadMarkedHistory(ReadMarking, ResumesSource):
    """A history whose painted messages are acknowledged: the one map of painted evidence
    waiting for Core, and the acknowledgement that retires it. A mixin beside the native
    history, so its hooks are declared without ABC's metaclass."""

    page_source: ReplaceablePageSource
    view: WireView

    def __init__(self, *args, **kwargs) -> None:
        self._painted_reads: dict[FragmentKey, EvidencedFragment] = {}
        self._last_sent_references: tuple[MessageReference, ...] = ()
        super().__init__(*args, **kwargs)

    @property
    def last_sent_references(self) -> tuple[MessageReference, ...]:
        """The most recent outgoing message's references, updated incrementally when
        pages commit — never a reverse scan of all fragments."""
        return self._last_sent_references

    def note_sent_references(self, fragments: tuple) -> None:
        """Check the given (new) fragments for the most recent sent references.
        Called by the page commit path with only the arriving fragments."""
        for fragment in reversed(fragments):
            if references := fragment.sent_references:
                self._last_sent_references = references
                return

    # Reading the bound source's first page; a frontend may show it.
    reading = False

    @classmethod
    def empty_page(cls):
        return PreparedWirePage.empty(WirePage.unread())

    def initialize_source(self, source: WireSource) -> None:
        """Bind the conversation to read; the first refresh draws its newest page."""
        self._painted_reads.clear()
        self.page_source.close()
        self.page_source = WirePageBuffer(source, self.page_source.through, self.app.preparation,
                                          revision=UnobservedConversation(),
                                          fragments=source.fragments)

    @property
    def undrawn(self) -> bool:
        """Nothing of the bound source has been drawn yet."""
        return all(view.prepared.page.after.requires_read() for view in self.pages)

    @property
    def source_identity(self):
        # Growth of the bus is not another source: reads ahead stay valid.
        return self.page_source.reload_key(), self.selected_categories

    async def source_is_current(self, snapshot: HistorySourceSnapshot) -> bool:
        """Whether the route still selects this source's bus and nothing replaced the history."""
        source = self.page_source
        if not snapshot.current(self):
            return False
        return (await source.route_is_current()
                and source is self.page_source and snapshot.current(self))

    async def read_changes(self) -> bool:
        """Draw what changed in the source; False when the stores are as last drawn."""
        source = self.page_source
        self.reading = self.undrawn
        try:
            observed = await source.observe_changes(source.revision)
            if source is not self.page_source:
                return False
            return await observed.apply(self, source)
        finally:
            self.reading = False

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        if self.can_draw_on_screen:
            self.mark_visible()
            self.follow_message_style()

    def follow_message_style(self) -> None:
        """Draw the messages in the style the view's settings now name (its override, else
        the app's), once the history can draw: a change made while it could not is drawn
        when it next lays out. The drawn style is the source's; nothing else remembers it."""
        style = self.view.configuration_state.fields.ui.message_style
        if self.can_draw_on_screen and self.page_source.style_differs(style):
            self.schedule_source_work(partial(self.restyle, style()))

    def source_resumed(self) -> None:
        super().source_resumed()
        self.mark_visible()

    async def toggle_style(self) -> None:
        """Draw every message in the other style, here and in pages read from now on."""
        await self.page_source.change_style(self)

    async def restyle(self, style) -> None:
        """Draw every message in ``style`` (the message-style setting changed)."""
        await self.page_source.restyle_to(self, style)

    @abstractmethod
    def mark_visible_after_paint(self) -> None:
        """Try marking read again once the frontend has painted its next frame."""

    @abstractmethod
    def withdraw_view(self) -> None:
        """The route no longer reads this conversation: stop showing it."""

    @abstractmethod
    async def refresh_source(self) -> None:
        """Read the conversation again, as the view reads it now."""

    def retain_painted(self, fragment: EvidencedFragment) -> None:
        """Keep actual painted evidence until its original page is acknowledged."""
        if fragment.evidence is not None and self._painted_reads.get(fragment.key) is not fragment:
            self._painted_reads[fragment.key] = fragment
            self.mark_visible_after_paint()

    def retire_painted(self, fragments: tuple[EvidencedFragment, ...], proof: MessagePage) -> None:
        """Release only these receipts, never a newer paint of the same message."""
        for fragment in fragments:
            if fragment.evidence is proof:
                fragment.evidence = None
                if self._painted_reads.get(fragment.key) is fragment:
                    del self._painted_reads[fragment.key]

    def read_fragments(self) -> tuple[EvidencedFragment, ...]:
        if not self.is_attached or not self.can_draw_on_screen:
            return ()
        return tuple(self._painted_reads.values())

    def read_visible(self) -> PaintedRead:
        if not self.is_attached:
            return NothingToRead()
        if not any(fragment.evidence is not None for fragment in self.read_fragments()):
            return NothingToRead()
        return self.page_source.painted_read(self)

    async def _mark_read(self, snapshot: HistorySourceSnapshot) -> None:
        if not await self.source_is_current(snapshot):
            if snapshot.current(self):
                self.withdraw_view()
            elif self.is_attached:
                self.mark_visible_after_paint()
            return
        seen = tuple(fragment for fragment in self.read_fragments() if fragment.evidence is not None)
        if (selected := self.page_source.seen_page(self, seen)) is not None:
            await self._mark_page(*selected, snapshot)

    async def _mark_page(
        self, page: MessagePage, marked: tuple[EvidencedFragment, ...], snapshot: HistorySourceSnapshot
    ) -> None:
        source = self.page_source
        proof = marked[0].evidence
        try:
            await source.mark_page(page)
            self.retire_painted(marked, proof)
        except ReadAgain:
            # Every queued fragment carrying that same refused proof must
            # release it before reloading can paint a replacement. Keep
            # unrelated proofs and any newer paint already queued meanwhile.
            refused = tuple(fragment for fragment in self._painted_reads.values()
                            if fragment.evidence is proof)
            self.retire_painted((*marked, *refused), proof)
            # The viewer, peer, channel scope or bus changed after the page
            # was read: draw the conversation as it is read now.
            if snapshot.current(self):
                await self.reload_notification_source()
        finally:
            if self.is_attached:
                self.mark_visible_after_paint()

    async def reload_notification_source(self) -> None:
        """Forget what was observed, so the next refresh reads the page and its cut afresh."""
        self.page_source.revision = UnobservedConversation()
        await self.refresh_source()


class WireView(ConversationActivity):
    """A frontend's view of one wire conversation, as its page source, its sends and its
    commands address it. A plain parent: each toolkit's widget metaclass would conflict
    with ABCMeta.

    Listed before the frontend's conversation class: a conversation answers these for a
    thread's transcript and its sources, and a wire view's page source answers them
    instead."""

    conversation: ConversationKind
    message_history: ReadMarkedHistory

    def begin_submission(self, owner, submission):
        """A channel or inbox message goes where this view's page source says."""
        return self.message_history.page_source.begin_submission(self, owner, submission)

    async def command_target_context(self):
        """Commands address the conversation this view's page source reads."""
        return self.message_history.page_source.command_context(self)

    def status_thread(self):
        """Peer status does not grant access to the peer's transcript: the page source opens it."""
        return self.message_history.page_source.status_thread(self.app.coordination_access)

    def history_loading(self) -> bool:
        """The wire history is reading its first page."""
        return self.message_history.reading

    @property
    @abstractmethod
    def mode(self) -> str:
        """The session this view belongs to, as commands target it."""

    def apply_message_style(self) -> None:
        """The message-style setting changed for this tab (its override or the app's): draw
        the bus messages in the style it now resolves to (the `message_style` effect)."""
        self.message_history.follow_message_style()

    @abstractmethod
    def shows(self, root: str | Path, conversation: ConversationKind) -> bool:
        """Whether this view is still open on this conversation, read from this root."""

    @abstractmethod
    async def show_sent(self, sent: MessageReference) -> None:
        """A message this view sent was accepted: draw it."""

    @abstractmethod
    async def _refresh_source(self) -> None:
        """Read what changed in the conversation and the view's status beside it."""

    dispatch_sync: Callable[[object], None]
    """Hand the view the references its label and commands are read from: its
    conversation's dispatch answers."""


@dataclass(frozen=True)
class WireCut(ABC):
    """A place between two wire messages, where a page begins or ends."""

    cursor: PageCursor

    def same_position(self, other: WireCut) -> bool:
        return self == other

    def older(self) -> OlderTraversal:
        return self.cursor.older()

    def newer(self) -> NewerTraversal:
        return self.cursor.newer()

    # Whether a page read from this cut depends on how far the bus has grown.
    bounded: ClassVar[bool]
    # Whether a page read from this cut is kept for the next reader of the same page.
    kept: ClassVar[bool]


@dataclass(frozen=True)
class BeforeMessage(WireCut):
    """Just before the message Core's cursor names; earlier messages never change."""

    bounded = False
    kept = True


@dataclass(frozen=True)
class AfterMessage(WireCut):
    """Just after the message Core's cursor names."""

    bounded = True
    kept = True

    def accepts(self, current: MessagePage, incoming: MessagePage) -> bool:
        return incoming.same_display(current)

    def advanced_source(self, current: MessagePage, incoming: MessagePage) -> MessagePage:
        return current

    def observed(self) -> AfterMessage:
        return self

    def requires_read(self) -> bool:
        return False


@dataclass(frozen=True)
class AfterSequence(AfterMessage):
    """After everything the bus held up to a sequence number, whoever it was for.

    The end of the conversation is read from here: each read is a new answer.
    """

    cursor: LiveCursor
    kept = False

    def older(self) -> OlderTraversal:
        return OlderTraversal(LiveCursor(self.cursor.sequence + 1))


@dataclass(frozen=True)
class NothingRead(AfterSequence):
    """Where the placeholder drawn before the first read ends.

    It reads like the start of the bus but never equals a cursor Core answered,
    so even an empty bus is read once instead of taken as already drawn.
    """

    cursor: LiveCursor = field(default_factory=lambda: LiveCursor(0))

    def accepts(self, current: MessagePage, incoming: MessagePage) -> bool:
        return True

    def advanced_source(self, current: MessagePage, incoming: MessagePage) -> MessagePage:
        return incoming

    def observed(self) -> AfterSequence:
        return AfterSequence(self.cursor)

    def requires_read(self) -> bool:
        return True


@dataclass(frozen=True)
class WirePage:
    """One page as the line history pages it; `source` is Core's page with its read evidence."""

    events: tuple[Message, ...]
    before: BeforeMessage | None
    after: AfterMessage
    has_older: bool
    has_newer: bool
    source: MessagePage

    @classmethod
    def unread(cls) -> WirePage:
        """The declared unread cursor carries an empty, unscoped placeholder."""
        return cls((), None, NothingRead(), False, False, MessagePageRequest.empty)

    def accepts(self, page: MessagePage) -> bool:
        """An initial placeholder accepts its first scope; Core compares actual pages."""
        return self.after.accepts(self.source, page)

    def advanced(self, interval: WirePage, *, older: bool) -> WirePage:
        """An empty interval advances its cut and establishes the first Core page.

        Existing fragments retain their original page evidence; a placeholder
        must adopt the actual empty Core page rather than remain unobserved.
        """
        source = self.after.advanced_source(self.source, interval.source)
        return (
            replace(self, before=interval.before, after=self.after.observed(),
                    has_older=interval.has_older, source=source)
            if older
            else replace(self, after=interval.after, has_newer=interval.has_newer, source=source)
        )


class PreparedWirePage(PreparedTranscriptPage):
    """Wire intervals preserve Core's original display page when advanced empty."""

    def advance_empty(self, prepared: PreparedTranscriptPage, older: bool) -> None:
        self.page = self.page.advanced(prepared.page, older=older)


@dataclass(frozen=True, eq=False)
class WireSource(BusQueueSource, ConversationSource):
    """One conversation as one viewer reads it from Core, and how its messages are styled.

    A page read to the newest messages is short so that it is drawn at once;
    every other read takes a whole transport page.
    """

    root: Path
    conversation: ConversationKind
    project: Checkout
    me: str
    style: WireMessageStyle
    access: CoordinationAccess = field(kw_only=True)
    core: CoreAccess = field(kw_only=True)
    fragments: type[EvidencedFragment] = field(kw_only=True)
    tail_limit: int = 8
    page_limit: int = 40

    def observe(self, seen: ConversationObservation) -> SourceObservation:
        """The observed state owns how changed or unchanged history is drawn."""
        revision = self.core.call(CommsConversationRevisionTool(
            conversation=self.conversation.retained_target(), project=self.project, seen=seen))
        if revision == seen:
            return Unchanged()
        high = AfterSequence(self.core.call(CommsLatestSequenceTool()).cursor)
        # Core's display view owns which stores can replace this reading.
        # Notification/read/activity writes do not require a page to learn that.
        observation = ReplacedWireObservation if revision.display_changed_since(seen) else GrowingWireObservation
        return observation(revision, high)

    def read(self, request: PageRequest[WireCut], through: AfterSequence) -> PreparedTranscriptPage:
        """Read the page a request names, never past `through`, as fragments to draw."""
        page = request.end.wire_page(self, request.cursor, through)
        # A re-read message starts from its last known notifications, never from
        # "Checking": the answer that follows then changes nothing it has to redraw.
        scope = ReadNotifications(str(self.root), LiveNotificationRead(()),
                                  display=page.selection.notification_identity)
        files = PageFiles.read(str(self.root), self.core, (
            (message.reference, MessageRow(message, self.me).file_reader) for message in page.messages))
        fragments = tuple(
            self.fragments.of(message, shown=MessageShown(
                style=self.style,
                status=self.access.notification_status(scope, message.role.notification_references(message))),
                evidence=evidence, reader=self.me, page=page, files=files.of(message.reference))
            for message, evidence in page.message_evidence()
        )
        wire = WirePage(
            page.messages,
            BeforeMessage(page.messages[0].view_cursor) if page.messages else None,
            AfterMessage(page.messages[-1].view_cursor) if page.has_newer and page.messages else through.observed(),
            page.has_older and bool(page.messages),
            page.has_newer and bool(page.messages),
            page,
        )
        return PreparedWirePage.measured(wire, fragments)

    def restyled(self, style: WireMessageStyle) -> WireSource:
        return replace(self, style=style)


@dataclass(frozen=True)
class RestyledViewportRequest(ReplacementViewportRequest):
    loader: WireSource

    def source(self, owner):
        return WirePageBuffer(
            self.loader, owner.page_source.through, owner.page_source.runtime,
            revision=owner.page_source.revision, fragments=owner.page_source.fragments,
        )


@dataclass(frozen=True)
class ObservedViewportRequest(ReplacementViewportRequest):
    observation: WireObservation

    def source(self, owner):
        source = owner.page_source.replacement(self.observation.through)
        source.revision = self.observation.revision
        return source


@dataclass(frozen=True)
class WireObservation(SourceObservation):
    revision: ConversationRevision
    through: AfterSequence


class ReplacedWireObservation(WireObservation):
    async def apply(self, history: ReadMarkedHistory, source: ReplaceablePageSource) -> bool:
        return await history.show_newest(ObservedViewportRequest(LatestPosition.hold(history.window), self))


class GrowingWireObservation(WireObservation):
    async def apply(self, history, source) -> bool:
        if not history.undrawn:
            published = await history.extend(self.through)
        else:
            history.extend_source(self.through)
            published = await super().apply(history, source)
        if published and history.page_source is source:
            source.revision = self.revision
        return published


@dataclass(frozen=True)
class WirePageWork(SourcePageWork[WireCut]):
    """Read one wire page off the UI thread; `loader` is the WireSource."""

    @property
    def retain_result(self) -> bool:
        return self.request.cursor.kept

    async def execute(self, runtime, key):
        prepared = await runtime.run_thread(self.loader.read, self.request, self.through)
        if self.scope.closed:
            raise asyncio.CancelledError
        return await runtime.run_thread(self.finish_result, key, prepared)


@dataclass(frozen=True)
class ChannelDestination(BusDestination):
    """A channel or inbox page: shown while its view still reads this conversation from this
    root. A page reader the view replaces (a refresh, the next page) still shows it."""

    view: WireView

    def shown(self) -> bool:
        return self.view.shows(self.root, self.conversation)

    async def presented(self, sent: MessageReference) -> None:
        await self.view.show_sent(sent)


class WirePageBuffer(SavedHistory):
    """The line history's page reader over a wire source."""

    loader: WireSource

    def read_task(self, request: PageRequest) -> WirePageWork:
        """WireSource prepares its fragments; wire work needs no transcript renderer."""
        return WirePageWork(self.scope, self.loader, self.through, request)

    def __init__(self, *args, revision: ConversationObservation, **kwargs):
        super().__init__(*args, **kwargs)
        self.revision = revision

    def replacement(self, through) -> WirePageBuffer:
        return type(self)(self.loader, through, self.runtime,
                          revision=self.revision, fragments=self.fragments)

    def reads_from(self, root: str | Path) -> bool:
        return self.loader.root == root

    def uses_observation(self, observation: Observation) -> bool:
        return observation.observes(self.loader.root)

    async def route_is_current(self) -> bool:
        return not self.closed and await self.runtime.run_thread(
            lambda: self.loader.access.current(self.loader.root)
        )

    def status_thread(self, access):
        return self.loader.conversation.status_thread(self.loader.root, access)

    def refresh_identity(self, view: WireView) -> None:
        """Dispatch the references of this source's own root: the source the view was opened on."""
        view.dispatch_sync(view.app.coordination_access.reference_context(str(self.loader.root)))

    def command_context(self, view):
        loader = self.loader
        return TargetContext.in_conversation(view.app, loader.root, loader.conversation, loader.me,
                                             loader.project, view.mode)

    def begin_submission(
        self, view: WireView, owner: SubmissionOwner, submission: SubmittedText
    ) -> SubmissionStart:
        """A channel or inbox message queues behind the view's earlier ones; compose stays open."""
        return owner.start_bus(submission, ChannelDestination(self.loader.root, self.loader.conversation, view))

    def schedule_refresh(self, view: WireView):
        history = view.message_history
        return history.schedule_source_work(view._refresh_source)

    def painted_read(self, history: ReadMarkedHistory) -> PaintedRead:
        return ReadWork(history._mark_read(history.source_snapshot()))

    async def change_style(self, history: ReadMarkedHistory) -> None:
        await self.restyle_to(history, self.loader.style.next())

    def style_differs(self, style) -> bool:
        """Whether the messages are drawn in a style other than ``style``."""
        return type(self.loader.style) is not style

    async def restyle_to(self, history: ReadMarkedHistory, style) -> None:
        """Draw every message in ``style``, here and in pages read from now on."""
        if not history.can_draw_on_screen or type(style) is type(self.loader.style):
            return
        await history.show_newest(
            RestyledViewportRequest(LatestPosition.hold(history.window), self.loader.restyled(style))
        )

    async def read_revision(self):
        return await self.runtime.run_thread(self.loader.wire_revision)

    async def observe_changes(self, revision):
        return await self.runtime.run_thread(self.loader.observe, revision)

    async def accept_page(self, history, edge, prepared) -> bool:
        if edge.prepared.page.accepts(prepared.page.source):
            return True
        prepared.configure(batch_size=len(prepared.fragments))
        await history.show_newest(
            LatestReplacementViewportRequest(LatestPosition.hold(history.window), self.through),
            arrivals=history._source_state.arriving(prepared, history.drawn_tail_followed),
        )
        return False

    def seen_page(self, history, seen):
        return self.loader.conversation.seen_page(seen)

    async def mark_page(self, page: MessagePage) -> None:
        await asyncio.to_thread(
            self.loader.core.call, CommsMarkPageReadTool(page=page, worktree=self.loader.project))

    async def compose_access(self) -> ComposeAccess:
        return await self.runtime.run_thread(self.loader.conversation.compose_access, self.loader.core)

    async def update_mentions(self, view: WireView) -> None:
        await self.loader.conversation.update_mentions(view, self.loader)

    async def status_text(self, *, read_only):
        return await self.loader.conversation.status_text(self.loader, read_only=read_only)

    def accepts(self, loader: WireSource, through) -> bool:
        # Earlier wire cuts stay valid while the bus grows.
        return self.loader is loader
