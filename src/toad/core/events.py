"""Declared application events and the lifetime of their subscribers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from weakref import WeakSet

from agent_comms.declared_family import DeclaredFamily


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
class McpClientStopped(CoreEvent):
    """The attached agent's owning connection stopped."""


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
