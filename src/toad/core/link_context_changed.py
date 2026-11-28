from __future__ import annotations

from dataclasses import dataclass
from weakref import WeakSet, WeakValueDictionary

from agent_comms.nominal.declared_family import DeclaredFamily
from formbridge.publications import PublicationStream, Subscription


class CoreEvent(DeclaredFamily, affix="Event"):
    """An application publication; its wire shape belongs to FieldCodec."""

    def accepted_by(self, handler: object, message: Publication) -> bool:
        """Whether a conversation comms handler accepts this publication."""
        return True

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


@dataclass(frozen=True)
class LinkContextChanged(CoreEvent):
    """The original project or reference observation changed; redraw from its owner."""


class Publication:
    """One delivered Core event and the subscription it arrived on. Each frontend's carrier
    is one; who published it follows from the subscription's stream."""

    event: CoreEvent
    subscription: Subscription

    @property
    def publisher(self) -> object:
        return self.subscription.stream.publisher


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
