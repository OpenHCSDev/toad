"""Declared application events and the lifetime of their subscribers."""

from __future__ import annotations

from collections.abc import Callable
from abc import abstractmethod
from dataclasses import InitVar, dataclass, field
from pathlib import Path
from typing import Annotated
from weakref import WeakMethod, WeakSet, ref

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import PathText
from agent_comms.presentation import WireRevision
from agent_comms.transcript_sources import AssignedSourceIdentity
from toad.plan import PlanItem
from toad.acp.status import ToolCallStatus
from toad.acp.sdk_boundary import ToolCallWire
from toad.live_output import OutputStream
from agent_comms.acp_extension import AgentCommsUpdate, QueueScope, RequestFailedUpdate
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation


class CoreEvent(DeclaredFamily, affix="Event"):
    """An application publication; its wire shape belongs to FieldCodec."""

    def can_replace(self, event: CoreEvent) -> bool:
        """Only declared coalescing invalidations replace queued publications."""
        return False


@dataclass(frozen=True)
class ThreadIdentityChanged(CoreEvent):
    """The originating session's current thread or wire changed."""

    view: object

    def can_replace(self, event: CoreEvent) -> bool:
        return isinstance(event, ThreadIdentityChanged) and event.view is self.view


@dataclass(frozen=True)
class Update(CoreEvent):
    """The original stream owns grouping; its native block is not wire data."""

    type: str
    text: str
    stream: OutputStream


@dataclass(frozen=True)
class CommsUpdated(CoreEvent):
    """The original typed publication retains its emission-time context."""

    update: AgentCommsUpdate | QueuePresentation | CursorPresentation
    session_id: str | None = None
    sequence: int | None = None
    recover_draft: bool = False
    queue_scope: QueueScope | None = None


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

    @property
    def tool_id(self) -> str:
        from toad.acp.encode_tool_call_id import encode_tool_call_id
        return encode_tool_call_id(self.tool_call.call.tool_call_id)


@dataclass(frozen=True)
class SessionChangedEvent(CoreEvent):
    """Invalidate a session projection; SessionTracker owns the current details."""

    mode_name: str


@dataclass(frozen=True)
class SessionClosedEvent(SessionChangedEvent):
    """The original session was removed from SessionTracker."""


@dataclass(frozen=True)
class SessionSelected(CoreEvent):
    """The original application completed this mode transition."""

    mode_name: str
    previous_mode: str


@dataclass(frozen=True)
class OpenTabsChanged(CoreEvent):
    """Read the open sessions and tab order again."""

    def can_replace(self, event: CoreEvent) -> bool:
        # No transition payload belongs to this invalidation. Its receivers
        # read the currently open sessions; adjacent identical requests need one
        # publication, not another traversal for each busy recipient.
        return self == event


@dataclass(frozen=True)
class TabHistoryChanged(CoreEvent):
    """The original TabOrder changed its navigation history."""


@dataclass(frozen=True)
class ThreadRowStateChanged(CoreEvent):
    """Something this app shows on thread rows changed: a pending action or an open session's state."""


@dataclass(frozen=True)
class CoordinationObserved(CoreEvent):
    """Core's stores changed; the revision Core observed, None without a service.

    Consumers ask the revision what changed (Core answers) instead of
    re-reading every store on every observation.
    """

    revision: WireRevision | None

    def can_replace(self, event: CoreEvent) -> bool:
        # A newer observation supersedes a pending older one. The native
        # carrier still never replaces an intervening input or Comms update.
        return isinstance(event, CoordinationObserved)


@dataclass(frozen=True)
class ExternalTranscriptChanged(CoreEvent):
    """A CLI published text; its open transcript reads the current source."""

    def can_replace(self, event: CoreEvent) -> bool:
        return self == event


@dataclass(frozen=True)
class Thinking(CoreEvent):
    type: str
    text: str


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
class LinkContextChanged(CoreEvent):
    """The original project or reference observation changed; redraw from its owner."""


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
        from toad.widgets.note import Note

        if self.message:
            error = Content.assemble(
                Content.from_markup(self.message).stylize("$text-error"),
                " — ",
                Content(self.details.strip()).stylize("dim"),
            )
        else:
            error = Content(self.details.strip()).stylize("$text-error")
        await view.post(Note(error, classes="-error"))


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
        from toad.project_link import AcpLogLink
        from toad.widgets.agent_response import AgentResponse
        from toad.widgets.message_filter import OtherCategory

        link = AgentResponse(AcpLogLink.markdown(self.log_path),
                             show_divider=False, category=OtherCategory)
        link.add_class("-error-log-link")
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


@dataclass(eq=False)
class Subscription:
    """A subscriber owns this resource for as long as it wants publications."""

    stream: CoreEventStream
    event_type: type[CoreEvent]
    listener: InitVar[Callable[[CoreEvent, Subscription], object]]
    _listener: Callable[[], Callable[[CoreEvent, Subscription], object] | None] = field(init=False, repr=False)

    def __post_init__(self, listener) -> None:
        # Python owns these two callable forms. A borrowed bound receiver must
        # stay weak; a standalone listener belongs to this subscriber resource.
        try:
            self._listener = WeakMethod(listener)
        except TypeError:
            self._listener = lambda: listener

    def publish(self, event: CoreEvent) -> None:
        listener = self._listener()
        if listener is None:
            self.close()
        elif self.active:
            listener(event, self)

    @property
    def active(self) -> bool:
        return self in self.stream.subscriptions

    def accepts(self, original: Subscription) -> bool:
        return self is original and self.active

    def close(self) -> None:
        self.stream.subscriptions.discard(self)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class CoreEventStream:
    """Publish original events; neither retain state nor schedule frontend work."""

    def __init__(self, publisher: object) -> None:
        self._publisher = ref(publisher)
        self.subscriptions: WeakSet[Subscription] = WeakSet()

    @property
    def publisher(self) -> object:
        publisher = self._publisher()
        if publisher is None:
            raise RuntimeError("The publication resource outlived its original owner")
        return publisher

    def subscribe(self, event_type: type[CoreEvent],
                  listener: Callable[[CoreEvent, Subscription], object]) -> Subscription:
        subscription = Subscription(self, event_type, listener)
        self.subscriptions.add(subscription)
        return subscription

    def publish(self, event: CoreEvent) -> None:
        for subscription in tuple(self.subscriptions):
            if isinstance(event, subscription.event_type):
                subscription.publish(event)
