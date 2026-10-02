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


@dataclass(eq=False)
class Subscription:
    """A subscriber owns this resource for as long as it wants publications."""

    stream: CoreEventStream
    listener: Callable[[CoreEvent], object]

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

    def subscribe(self, listener: Callable[[CoreEvent], object]) -> Subscription:
        subscription = Subscription(self, listener)
        self.subscriptions.add(subscription)
        return subscription

    def publish(self, event: CoreEvent) -> None:
        for subscription in tuple(self.subscriptions):
            subscription.listener(event)
