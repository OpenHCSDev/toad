"""The Textual message pump carries application publications unchanged."""

from agent_comms.mro_dispatch import MroDispatch
from textual.message import Message

from toad.core.events import CoreEvent, CoreEventStream, Subscription


class CoreEventMessage(Message):
    """One frontend carrier, independent of the event's nominal case."""

    def __init__(self, event: CoreEvent, subscription: Subscription) -> None:
        super().__init__()
        self.event = event
        self.subscription = subscription


class CoreEventReceiver(MroDispatch):
    """Consume declared events inside the native message-pump lifetime."""

    def __init__(self, *args, **kwargs) -> None:
        self._core_subscriptions: set[Subscription] = set()
        super().__init__(*args, **kwargs)

    def subscribe_core(self, stream: CoreEventStream) -> Subscription:
        subscription = stream.subscribe(self.post_core_event)
        self._core_subscriptions.add(subscription)
        return subscription

    def retire_core(self, subscription: Subscription) -> None:
        subscription.close()
        self._core_subscriptions.discard(subscription)

    def post_core_event(self, event: CoreEvent, subscription: Subscription) -> bool:
        return self.post_message(CoreEventMessage(event, subscription))

    async def on_core_event_message(self, message: CoreEventMessage) -> None:
        message.stop()
        if not message.subscription.active:
            return
        handlers = tuple(self.handlers_for(message.event))
        if not handlers:
            raise TypeError(f"No core event handler on {type(self).__name__}: {type(message.event).__name__}")
        await self.consume_handlers(message.event, handlers)

    def _on_unmount(self) -> None:
        for subscription in self._core_subscriptions:
            subscription.close()
        self._core_subscriptions.clear()
