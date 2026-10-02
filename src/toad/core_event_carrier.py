"""The Textual message pump carries application publications unchanged."""

from agent_comms.mro_dispatch import MroDispatch
from textual._callback import invoke
from textual.message import Message
from weakref import WeakMethod, ref
from functools import cached_property

from toad.core.events import CoreEvent, CoreEventStream, Subscription


async def dispatch_publication(receiver, message) -> None:
    await receiver.consume_handlers(message, receiver.handlers_for(message.event))


class CoreEventMessage(Message):
    """One frontend carrier, independent of the event's nominal case."""

    def __init__(self, event: CoreEvent, subscription: Subscription,
                 consume=dispatch_publication) -> None:
        super().__init__()
        self.event = event
        self.subscription = subscription
        # The native pump owns this delivery callback, never the wire event.
        self.consume = consume

    @property
    def publisher(self) -> object:
        return self.subscription.stream.publisher

    def can_replace(self, message: Message) -> bool:
        return (isinstance(message, CoreEventMessage)
                and self.subscription is message.subscription
                and self.event.can_replace(message.event))


class CoreEventReceiver(MroDispatch):
    """Consume declared events inside the native message-pump lifetime."""

    def __init__(self, *args, **kwargs) -> None:
        self._core_subscriptions: set[Subscription] = set()
        super().__init__(*args, **kwargs)

    def subscribe_core(self, stream: CoreEventStream) -> Subscription:
        subscription = stream.subscribe(self.post_core_event)
        self._core_subscriptions.add(subscription)
        return subscription

    @cached_property
    def core_publications(self) -> CoreEventStream:
        """Acquire this native source's publication resource on first use."""
        stream = CoreEventStream(self)
        self.subscribe_core(stream)
        return stream

    def publish_core(self, event: CoreEvent) -> None:
        self.core_publications.publish(event)

    async def consume_handlers(self, message, handlers):
        # Textual callbacks may return native Worker resources. Publications
        # retain their identity; callback returns do not replace their data.
        for handler in handlers:
            await invoke(handler, message)
        return message

    def observe_core(self, stream: CoreEventStream) -> Subscription:
        """Broadcast observations terminate at their original native recipient."""
        for subscription in self._core_subscriptions:
            if subscription.stream is stream and subscription.active:
                return subscription
        subscription = stream.subscribe(self.post_core_observation)
        self._core_subscriptions.add(subscription)
        return subscription

    def retire_core(self, subscription: Subscription) -> None:
        subscription.close()
        self._core_subscriptions.discard(subscription)

    def retire_core_observations(self, stream: CoreEventStream) -> None:
        for subscription in tuple(self._core_subscriptions):
            if subscription.stream is stream:
                self.retire_core(subscription)

    def observe_core_callback(self, stream: CoreEventStream, callback) -> Subscription:
        """An original deferred operation receives relief inside its native pump."""
        recipient = ref(self)
        try:
            borrowed_callback = WeakMethod(callback)
        except TypeError:
            borrowed_callback = lambda: callback

        async def consume(receiver, message) -> None:
            callback = borrowed_callback()
            if callback is not None:
                await invoke(callback, message.event)

        def publish(event, subscription) -> None:
            receiver = recipient()
            if receiver is None:
                subscription.close()
                return
            message = CoreEventMessage(event, subscription, consume)
            message.bubble = False
            receiver.post_message(message)

        subscription = stream.subscribe(publish)
        self._core_subscriptions.add(subscription)
        return subscription

    def post_core_event(self, event: CoreEvent, subscription: Subscription) -> bool:
        return self.post_message(CoreEventMessage(event, subscription))

    def post_core_observation(self, event: CoreEvent, subscription: Subscription) -> bool:
        message = CoreEventMessage(event, subscription)
        message.bubble = False
        return self.post_message(message)

    async def on_core_event_message(self, message: CoreEventMessage) -> None:
        if not message.subscription.active:
            message.stop()
            return
        await message.consume(self, message)

    def _on_unmount(self) -> None:
        for subscription in self._core_subscriptions:
            subscription.close()
        self._core_subscriptions.clear()
