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
from toad.plan import PlanItem
from toad.acp.status import ToolCallStatus
from toad.acp.sdk_boundary import ToolCallWire
from toad.live_output import OutputStream
from agent_comms.acp_extension import AgentCommsUpdate, QueueScope
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation


class CoreEvent(DeclaredFamily, affix="Event"):
    """An application publication; its wire shape belongs to FieldCodec."""

    def can_replace(self, event: CoreEvent) -> bool:
        """Only declared coalescing invalidations replace queued publications."""
        return False


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
    """An ordered snapshot of the original admitted plan items."""

    entries: list[PlanItem]


@dataclass(frozen=True)
class ToolCall(CoreEvent):
    """The original tool owner assembled this exact SDK call snapshot."""

    tool_call: Annotated[ToolCallStatus, ToolCallWire]

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


@dataclass(frozen=True)
class OpenTabsChanged(CoreEvent):
    """Read the original session admissions and tab order again."""


@dataclass(frozen=True)
class TabHistoryChanged(CoreEvent):
    """The original TabOrder changed its navigation history."""


@dataclass(frozen=True)
class ThreadActionsChanged(CoreEvent):
    """The original application changed an admitted thread action."""


@dataclass(frozen=True)
class SidebarLayoutChanged(CoreEvent):
    """The original sidebar layout changed; native panes derive their paint."""


@dataclass(frozen=True)
class CoordinationObserved(CoreEvent):
    """The original route/revision observer permits another guarded read."""


@dataclass(frozen=True)
class Thinking(CoreEvent):
    type: str
    text: str


@dataclass(frozen=True)
class UserMessage(CoreEvent):
    """An admitted external user chunk; history keeps its original authority."""

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
class SessionSubtitleChanged(CoreEvent):
    subtitle: str


@dataclass(frozen=True)
class SessionPathChanged(CoreEvent):
    path: str


@dataclass(frozen=True)
class ThreadActivityChanged(CoreEvent):
    """Invalidate feedback from the original observation resource."""


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


@dataclass(frozen=True)
class AgentFail(CoreEvent):
    """Agent failed to start."""

    message: str
    details: str = ""


class HelpAgentFail(AgentFail):
    @property
    @abstractmethod
    def help_text(self) -> str: ...

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


@dataclass(frozen=True)
class LogAgentFail(AgentFail):
    log_path: Annotated[Path, PathText] = field(kw_only=True)

@dataclass(eq=False)
class Subscription:
    """A subscriber owns this resource for as long as it wants publications."""

    stream: CoreEventStream
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

    def subscribe(self, listener: Callable[[CoreEvent, Subscription], object]) -> Subscription:
        subscription = Subscription(self, listener)
        self.subscriptions.add(subscription)
        return subscription

    def publish(self, event: CoreEvent) -> None:
        for subscription in tuple(self.subscriptions):
            subscription.publish(event)
