"""The Textual message pump carries application publications unchanged."""

from agent_comms.mro_dispatch import MroDispatch
from textual._callback import invoke
from textual.message import Message
from functools import cached_property, partial
from dataclasses import InitVar, dataclass, field

from toad.core.events import CoreEvent, CoreEventStream, Subscription, ThreadChangeSubscription


async def dispatch_publication(receiver, message) -> None:
    await receiver.consume_handlers(message, receiver.handlers_for(message.event))


class CoreEventMessage(Message):
    """One frontend carrier, independent of the event's nominal case."""

    def __init__(self, event: CoreEvent, subscription: Subscription,
                 consume=dispatch_publication) -> None:
        super().__init__()
        self.event = event
        self.subscription = subscription
        self._publisher = subscription.stream.publisher
        # The native pump owns this delivery callback, never the wire event.
        self.consume = consume

    @property
    def publisher(self) -> object:
        return self._publisher

    def can_replace(self, message: Message) -> bool:
        return (isinstance(message, CoreEventMessage)
                and self.subscription is message.subscription
                and self.event.can_replace(message.event))


@dataclass(eq=False)
class CallbackSubscription(Subscription):
    callback: InitVar[object] = field(kw_only=True)
    _callback: object = field(init=False, repr=False)

    def __post_init__(self, listener, callback) -> None:
        super().__post_init__(listener)
        self._callback = self.weak_method(callback)

    async def consume(self, receiver, message) -> None:
        callback = self._callback()
        if callback is not None:
            await invoke(callback, message.event)


@dataclass(eq=False)
class ThreadCallbackSubscription(ThreadChangeSubscription, CallbackSubscription):
    """Compose thread indexing with callback delivery in the native pump."""


class CoreEventReceiver(MroDispatch):
    """Consume declared events inside the native message-pump lifetime."""

    def __init__(self, *args, **kwargs) -> None:
        self._core_subscriptions: set[Subscription] = set()
        super().__init__(*args, **kwargs)

    def subscribe_core(self, stream: CoreEventStream) -> Subscription:
        subscription = stream.subscribe(CoreEvent, self.post_core_event)
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

    def accepts(self, message: CoreEventMessage) -> bool:
        return True

    async def consume_handlers(self, message, handlers, *args, **kwargs):
        # Textual callbacks may return native Worker resources. Publications
        # retain their identity; callback returns do not replace their data.
        for handler in handlers:
            await invoke(partial(handler, **kwargs), message, *args)
        return message

    def observe_core(self, stream: CoreEventStream) -> Subscription:
        """Broadcast observations terminate at their original native recipient."""
        for subscription in self._core_subscriptions:
            if (subscription.stream is stream and subscription.event_type is CoreEvent
                    and subscription.active):
                return subscription
        subscription = stream.subscribe(CoreEvent, self.post_core_observation)
        self._core_subscriptions.add(subscription)
        return subscription

    def retire_core(self, subscription: Subscription) -> None:
        subscription.close()
        self._core_subscriptions.discard(subscription)

    def retire_core_observations(self, stream: CoreEventStream) -> None:
        for subscription in tuple(self._core_subscriptions):
            if subscription.stream is stream:
                self.retire_core(subscription)

    def observe_core_callback(self, stream: CoreEventStream,
                              event_type: type[CoreEvent], callback, *,
                              factory=CallbackSubscription) -> Subscription:
        """An original deferred operation receives relief inside its native pump."""
        subscription = stream.subscribe(
            event_type, self.post_core_callback, factory=partial(factory, callback=callback))
        self._core_subscriptions.add(subscription)
        return subscription

    def post_core_callback(self, event: CoreEvent, subscription: CallbackSubscription) -> bool:
        message = CoreEventMessage(event, subscription, subscription.consume)
        message.bubble = False
        return self.post_message(message)

    def post_core_event(self, event: CoreEvent, subscription: Subscription) -> bool:
        message = CoreEventMessage(event, subscription)
        # Textual records whichever widget's handler is running as the sender
        # and stops a bubbling message at that widget. This widget publishes
        # the event, so an ancestor that asked for it (a menu choice run by
        # the conversation) still lets it travel on to the screen.
        message._sender = self
        return self.post_message(message)

    def post_core_observation(self, event: CoreEvent, subscription: Subscription) -> bool:
        message = CoreEventMessage(event, subscription)
        message.bubble = False
        return self.post_message(message)

    async def on_core_event_message(self, message: CoreEventMessage) -> None:
        if not message.subscription.active:
            message.stop()
            return
        if not self.accepts(message):
            message.stop()
            return
        await message.consume(self, message)

    def close_core_events(self) -> None:
        """End this receiver's subscriptions before its logical source disappears."""
        while self._core_subscriptions:
            self._core_subscriptions.pop().close()

    def _message_pump_closing(self) -> None:
        # Native shutdown also releases receivers without a logical session.
        self.close_core_events()
        super()._message_pump_closing()
