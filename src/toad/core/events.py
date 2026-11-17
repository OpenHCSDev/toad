"""Declared application events and the lifetime of their subscribers."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Annotated, ClassVar
from weakref import WeakSet, WeakValueDictionary

from formbridge.publications import (
    PublicationStream,
    Subscription,
)

from agent_comms.acp_extension import (
    NoQueueScope,
    QueueScope,
)
from agent_comms.acp_extension import AgentCommsUpdate
from agent_comms.acp_extension import RequestFailedUpdate
from agent_comms.messaging.sent_message import AssignedSourceIdentity
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import AcpSessionId, NoAcpSessionId, PathText
from agent_comms.presentation import ReadState
from agent_comms.team.team_hud import TeamHud

from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation
from toad.acp.sdk_boundary import ToolCallWire
from toad.acp.status import ToolCallStatus
from toad.live_output import OutputStream, ThoughtStream
from toad.plan import PlanItem
from toad.client.tab_identity import TabIdentity
from formbridge.operations import ExclusiveKind, OperationKind


class ThreadInterestUpdate(OperationKind, ExclusiveKind):
    """Tells Core which threads the open views are interested in; a newer update supersedes one running."""


class CoreEvent(DeclaredFamily, affix="Event"):
    """An application publication; its wire shape belongs to FieldCodec."""

    session_scoped: ClassVar[bool] = False

    def refreshes(self, screen: object) -> bool:
        """Whether this publication is the given screen's to act on.

        A publication owns what it means for the views that receive it, so a screen asks this
        question instead of classifying events by type. Every event is news to every screen
        unless its member says otherwise.
        """
        return True

    def subscribers(self, stream: CoreEventStream):
        for event_type in type(self).__mro__:
            yield from stream.subscriptions.get(event_type, ())

    def replaces(self, queued: CoreEvent) -> bool:
        """Only a CoalescingEvent replaces a queued publication."""
        return False

    def keyed_as(self, key: object) -> bool:
        """Only a queued CoalescingEvent carries a coalescing key."""
        return False


class CoalescingEvent(CoreEvent, declared_name=None):
    """A newer publication supersedes a queued one with an equal coalescing key.

    The native carrier still never replaces an intervening input or Comms update.
    """

    def coalescing_key(self) -> object:
        return type(self)

    def replaces(self, queued: CoreEvent) -> bool:
        return queued.keyed_as(self.coalescing_key())

    def keyed_as(self, key: object) -> bool:
        return self.coalescing_key() == key


@dataclass(frozen=True)
class ThreadIdentityChanged(CoalescingEvent):
    """The originating session's current thread or wire changed."""

    view: object

    def coalescing_key(self) -> object:
        return type(self), self.view


@dataclass(frozen=True)
class Update(CoreEvent):
    """The original stream owns grouping; its native block is not wire data."""

    type: str
    text: str
    stream: OutputStream


@dataclass(frozen=True)
class CommsUpdated(CoreEvent):
    """The original typed publication retains its emission-time context."""

    session_scoped = True

    update: AgentCommsUpdate | QueuePresentation | CursorPresentation
    session_id: AcpSessionId | NoAcpSessionId = NoAcpSessionId()
    sequence: int | None = None
    recover_draft: bool = False
    queue_scope: QueueScope = field(default_factory=NoQueueScope)


@dataclass(frozen=True)
class Plan(CoreEvent):
    """An ordered snapshot of the original accepted plan items."""

    entries: list[PlanItem]


@dataclass(frozen=True)
class ToolCall(CoreEvent):
    """The original tool owner assembled this exact SDK call snapshot."""

    tool_call: Annotated[ToolCallStatus, ToolCallWire]
    scope: AssignedSourceIdentity | None = None

    def in_native_source(self, scope):
        if self.scope is None:
            return scope is None
        return scope is not None and scope.same_publication_source(self.scope)


@dataclass(frozen=True)
class SessionChangedEvent(CoreEvent):
    """Invalidate a session projection; SessionTracker owns the current details."""

    identity: TabIdentity


@dataclass(frozen=True)
class SessionClosedEvent(SessionChangedEvent):
    """The original session was removed from SessionTracker."""


@dataclass(frozen=True)
class SessionSelected(CoreEvent):
    """The original application completed this mode transition."""

    mode_name: str
    previous_mode: str

    def refreshes(self, screen: object) -> bool:
        """Only the arriving tab: a switch is not news to the tabs left behind."""
        return screen.is_current


@dataclass(frozen=True)
class OpenTabsChanged(CoalescingEvent):
    """Read the open sessions and tab order again.

    No transition payload belongs to this invalidation. Its receivers read the
    currently open sessions; adjacent requests need one publication, not another
    traversal for each busy recipient.
    """


@dataclass(frozen=True)
class TabHistoryChanged(CoreEvent):
    """The original TabOrder changed its navigation history."""


@dataclass(frozen=True)
class NamedThreadRowsChanged(CoreEvent):
    """The named rows changed; tab membership belongs to OpenTabsChanged."""

    names: frozenset[str] = field()


@dataclass(frozen=True)
class ThreadRowStateChanged(NamedThreadRowsChanged):
    """App-owned state changed these thread rows."""


@dataclass(frozen=True)
class CoordinationObserved(CoalescingEvent):
    """Core's stores changed; NoRevision requests a first read without a service.

    Consumers ask the revision what changed (Core answers) instead of
    re-reading every store on every observation.
    """

    revision: ReadState


@dataclass(frozen=True)
class SidebarPresented(CoalescingEvent):
    """The sidebar's current observation is ready for every view of its counts."""


@dataclass(frozen=True)
class TeamHudChanged(CoalescingEvent):
    """The team heartbeat replaced its frames; Core derived every field."""

    huds: tuple[TeamHud, ...]


@dataclass(frozen=True)
class TeamHudFailed(CoalescingEvent):
    """Team rows are unavailable; the page retains its last good frame."""

    error: Exception


@dataclass(frozen=True)
class ExternalTranscriptChanged(CoalescingEvent):
    """A CLI published text; its open transcript reads the current source."""


@dataclass(frozen=True)
class Thinking(CoreEvent):
    type: str
    text: str
    stream: ThoughtStream = field(default_factory=ThoughtStream)


@dataclass(frozen=True)
class UserMessage(CoreEvent):
    """An accepted external user chunk; history keeps its original authority."""

    type: str
    text: str


@dataclass(frozen=True)
class SessionInfoUpdate(CoreEvent):
    """The agent supplied a title; a null title is an external ACP value."""

    title: str | None


@dataclass(frozen=True)
class SessionTitleChanged(CoreEvent):
    name: str


@dataclass(frozen=True)
class SessionThreadTitle(CoreEvent):
    """The coordination thread presented a title for this session.

    A name the user chose outranks it; consumers keep the user's name and
    adopt this one only where the user has not named the session.
    """

    title: str


@dataclass(frozen=True)
class SessionSubtitleChanged(CoreEvent):
    subtitle: str


@dataclass(frozen=True)
class SessionAgentAttached(CoreEvent):
    """The selected session's operational agent is now attached."""


@dataclass(frozen=True)
class ThreadRowsChanged(NamedThreadRowsChanged):
    """The observed model's original change set, under its source root."""

    root: str

    def subscribers(self, stream: CoreEventStream):
        for thread in self.names:
            yield from stream.thread_subscriptions.get((self.root, thread), ())
        yield from super().subscribers(stream)


@dataclass(frozen=True)
class LinkContextChanged(CoreEvent):
    """The original project or reference observation changed; redraw from its owner."""


@dataclass(frozen=True)
class ObservedServiceChanged(LinkContextChanged):
    """The access owner attached a replacement service, not just new references."""


@dataclass(frozen=True)
class SessionPathChanged(CoreEvent):
    path: str


@dataclass(frozen=True)
class InputDispositionsChanged(CoreEvent):
    """Invalidate delivery display; the producer ledger owns its contents."""


@dataclass(frozen=True)
class RequestPermission(CoreEvent):
    """The original permission controller has requests to present."""


@dataclass(frozen=True)
class RejectedSessionUpdate(CoreEvent):
    """The ACP boundary excluded an invalid external notification."""


@dataclass(frozen=True)
class UpdateStatusLine(CoreEvent):
    """The original agent's ContextMeasurement changed."""


@dataclass(frozen=True)
class ConfigurationChanged(CoreEvent):
    """The original agent's configuration changed."""


@dataclass(frozen=True)
class AvailableCommandsUpdate(CoreEvent):
    """The original controller's advertised commands changed."""


@dataclass(frozen=True)
class McpClientStopped(CoreEvent):
    """The attached agent's owning connection stopped."""


@dataclass(frozen=True, kw_only=True)
class AgentReady(CoreEvent):
    """The original ACP session handshake completed."""

    session_id: AcpSessionId
    reconnected: bool = False


class AgentFail(CoreEvent):
    """Failure feedback; its source owns any persistent presentation."""

    message: str
    details: str

    async def present_session(self, view) -> None:
        """Specialized setup/help feedback survives the session's failure label."""
        await self.present(view)

    async def present(self, view) -> None:
        from textual.content import Content

        from toad.widgets.note import ErrorNote

        if self.message:
            error = Content.assemble(
                Content.from_markup(self.message).stylize("$text-error"),
                " — ",
                Content(self.details.strip()).stylize("dim"),
            )
        else:
            error = Content(self.details.strip()).stylize("$text-error")
        await view.post(ErrorNote(error))


@dataclass(frozen=True)
class TextAgentFail(AgentFail):
    """A failure without a saved journal row owns its visible notice."""

    message: str
    details: str = ""


class HelpAgentFail(TextAgentFail):
    @property
    @abstractmethod
    def help_text(self) -> str: ...

    async def present(self, view) -> None:
        from toad.widgets.markdown_note import MarkdownNote

        await super().present(view)
        await view.post(MarkdownNote(self.help_text))

class UnsupportedResumeAgentFail(HelpAgentFail):
    help_text = """## Agent does not support resume

The agent or ACP adapter does not support resuming sessions.

Try updating to see if support has been added.

- Exit the app, and run `toad` again
- Select the agent and hit ENTER
- Click the dropdown, select "Update" or "Install" again
- Repeat the process to update the ACP adapter (if required)

If that fails, ask for help in [Discussions](https://github.com/batrachianai/toad/discussions)!
"""


class FailureLog:
    """Log access shared by failures without copying their feedback."""

    log_path: Path

    async def show_log(self, view) -> None:
        from agent_comms.ui_model.message_category import OtherCategory

        from toad.project_link import AcpLogLink
        from toad.widgets.agent_response import AgentResponse

        link = AgentResponse(AcpLogLink.markdown(self.log_path),
                             show_divider=False, category=OtherCategory)
        await view.post(link)


@dataclass(frozen=True)
class LogAgentFail(FailureLog, TextAgentFail):
    log_path: Annotated[Path, PathText] = field(kw_only=True)

    async def present_session(self, view) -> None:
        # MainScreen presents the current terminal failure. Retain its journal
        # link, not a second error panel that outlives a recovered session.
        await self.show_log(view)

    async def present(self, view) -> None:
        await super().present(view)
        await self.show_log(view)


@dataclass(frozen=True)
class RequestAgentFail(FailureLog, AgentFail):
    """The decoded request failure asks its source where feedback belongs."""

    update: RequestFailedUpdate
    log_path: Annotated[Path, PathText]

    @property
    def message(self) -> str:
        return self.update.failure.title

    @property
    def details(self) -> str:
        return self.update.failure.feedback

    async def present(self, view) -> None:
        if not self.update.source.retained_in_history:
            await super().present(view)
            await self.show_log(view)
            return
        # message_end precedes the journal append. The existing source observer
        # resolves the saved row and its time; this event mounts no tail copy.
        view.transcript.require_commit()
        # Session inspection keeps ACP log access independent of delivery notices.


class Publication:
    """One delivered Core event and the subscription it arrived on. Each frontend's carrier
    is one; who published it follows from the subscription's stream."""

    event: CoreEvent
    subscription: Subscription

    @property
    def publisher(self) -> object:
        return self.subscription.stream.publisher


@dataclass(eq=False)
class ThreadChangeSubscription(Subscription):
    """One live thread scope owns both delivery and observation interest."""

    stream: CoreEventStream
    scope: tuple[str, str] = field(kw_only=True)

    @cached_property
    def bucket(self) -> WeakSet[Subscription]:
        return self.stream.thread_subscriptions.setdefault(self.scope, WeakSet())

    def bucket_opened(self) -> None:
        publisher = self.stream.publisher
        publisher.app.run_operation(ThreadInterestUpdate, publisher.update_thread_interest)

    def bucket_emptied(self) -> None:
        self.bucket_opened()


class CoreEventStream(PublicationStream):
    """Core-specific publication stream with thread-scoped subscriptions."""

    def __init__(self, publisher: object) -> None:
        super().__init__(publisher)
        self.thread_subscriptions: WeakValueDictionary[tuple[str, str], WeakSet[Subscription]] = WeakValueDictionary()

    def close_threads(self) -> None:
        for bucket in tuple(self.thread_subscriptions.values()):
            for subscription in tuple(bucket):
                subscription.close()

    def observed_threads(self, root: str) -> frozenset[str]:
        return frozenset(thread for (source, thread), bucket in self.thread_subscriptions.items()
                         if source == root and bucket)

    def publish(self, event: CoreEvent) -> None:  # type: ignore[override]
        subscriptions = tuple(event.subscribers(self))
        for subscription in subscriptions:
            for listener in subscription.listeners():
                listener(event, subscription)
