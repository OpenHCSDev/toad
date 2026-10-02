"""Declared application events and the lifetime of their subscribers."""

from __future__ import annotations

from collections.abc import Callable
from abc import abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated
from weakref import WeakSet

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import PathText


class CoreEvent(DeclaredFamily, affix="Event"):
    """An application publication; its wire shape belongs to FieldCodec."""


@dataclass(frozen=True)
class SessionChangedEvent(CoreEvent):
    """Invalidate a session projection; SessionTracker owns the current details."""

    mode_name: str


@dataclass(frozen=True)
class SessionClosedEvent(SessionChangedEvent):
    """The original session was removed from SessionTracker."""


@dataclass(frozen=True)
class Thinking(CoreEvent):
    type: str
    text: str


@dataclass(frozen=True)
class SessionInfoUpdate(CoreEvent):
    """The agent supplied a title; a null title is an external ACP value."""

    title: str | None


@dataclass(frozen=True)
class InputDispositionsChanged(CoreEvent):
    """Invalidate delivery display; the producer ledger owns its contents."""


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
    @abstractmethod
    async def explain(self, view): ...


class HelpAgentFail(AgentFail):
    @property
    @abstractmethod
    def help_text(self) -> str: ...

    async def explain(self, view):
        from toad.widgets.markdown_note import MarkdownNote
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


@dataclass(frozen=True)
class LogAgentFail(AgentFail):
    log_path: Annotated[Path, PathText] = field(kw_only=True)

    async def explain(self, view):
        from urllib.parse import quote
        from toad.widgets.agent_response import AgentResponse
        from toad.widgets.message_filter import OtherCategory
        link = AgentResponse(f"[Open ACP log]({quote(str(self.log_path))})",
                             show_divider=False, category=OtherCategory)
        link.add_class("-error-log-link")
        await view.post(link)


@dataclass(eq=False)
class Subscription:
    """A subscriber owns this resource for as long as it wants publications."""

    stream: CoreEventStream
    listener: Callable[[CoreEvent, Subscription], object]

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

    def __init__(self) -> None:
        self.subscriptions: WeakSet[Subscription] = WeakSet()

    def subscribe(self, listener: Callable[[CoreEvent, Subscription], object]) -> Subscription:
        subscription = Subscription(self, listener)
        self.subscriptions.add(subscription)
        return subscription

    def publish(self, event: CoreEvent) -> None:
        for subscription in tuple(self.subscriptions):
            subscription.listener(event, subscription)
