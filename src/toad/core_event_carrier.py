"""The Textual message pump carries application publications unchanged."""

from textual._callback import invoke
from textual import on
from textual.message import DeclaredMessage, Message
from textual.dom import DOMNode
from functools import cached_property, partial

from toad.client.subscribers import CallbackSubscription, CoreObserverDispatch
from formbridge.publications import Subscription

from toad.core.events import CoreEvent, CoreEventStream, Publication


async def dispatch_publication(receiver, message) -> None:
    # A handler declared for a case receives that case. The carrier follows as
    # the second value, which only a handler declaring it as a parameter takes.
    event = message.event
    await receiver.consume_handlers(event, receiver.handlers_for(event), message)


class CoreEventMessage(Publication, DeclaredMessage):
    """One frontend carrier, independent of the event's nominal case."""

    def __init__(self, event: CoreEvent, subscription: Subscription,
                 consume=dispatch_publication) -> None:
        super().__init__()
        self.event = event
        self.subscription = subscription
        # The native pump owns this delivery callback, never the wire event.
        self.consume = consume

    def can_replace(self, message: Message) -> bool:
        return (isinstance(message, CoreEventMessage)
                and self.subscription is message.subscription
                and self.event.replaces(message.event))


class CoreEventReceiver(CoreObserverDispatch, DOMNode):
    """Consume declared events inside the native message-pump lifetime."""

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

    async def consume_handlers(self, event, handlers, *args, **kwargs):
        # Textual callbacks may return native Worker resources. Publications
        # retain their identity; callback returns do not replace their data.
        for handler in handlers:
            await invoke(partial(handler, **kwargs), event, *args)
        return event

    def observe_core(self, stream: CoreEventStream) -> None:
        """Observe the events this receiver handles; observing a stream again keeps its subscriptions.
        Broadcast observations terminate at their original native recipient."""
        self._observations.setdefault(stream, tuple(
            stream.subscribe(event, self.post_core_observation) for event in self.consumed_core_events()))

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

    @on(CoreEventMessage)
    async def consume_publication(self, message: CoreEventMessage) -> None:
        if not message.subscription.active:
            message.stop()
            return
        if not self.accepts(message):
            message.stop()
            return
        await message.consume(self, message)

    def _message_pump_closing(self) -> None:
        # Native shutdown also releases receivers without a logical session.
        self.close_core_events()
        super()._message_pump_closing()
