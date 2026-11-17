"""Callbacks implemented by native views that subscribe to Core observations."""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import InitVar, dataclass, field
from functools import cache, cached_property, partial

from agent_comms.messaging.message_notification import MessageNotification

from formbridge.publications import Subscription

from metaclass_registry.mro_dispatch import MroDispatch

from toad.core.events import CoreEvent, CoreEventStream, ThreadChangeSubscription


@dataclass(eq=False)
class CallbackSubscription(Subscription):
    """Delivers each event to one callback through the receiving view's own handler dispatch."""

    callback: InitVar[object] = field(kw_only=True)
    _callback: object = field(init=False, repr=False)

    def __post_init__(self, listener, callback) -> None:
        super().__post_init__(listener)
        self._callback = self.weak_method(callback)

    async def consume(self, receiver, message) -> None:
        callback = self._callback()
        if callback is not None:
            await receiver.consume_handlers(message.event, (callback,))


@dataclass(eq=False)
class ThreadCallbackSubscription(ThreadChangeSubscription, CallbackSubscription):
    """Compose thread indexing with callback delivery."""


class CoreObserver:
    """A native view that holds Core event subscriptions for as long as it is shown.

    It keeps which subscriptions it holds and retires them; the native view delivers each
    callback inside its own event loop (post_core_callback) and runs the handlers
    (consume_handlers).
    """

    # Whether the native view is still in its tree, and whether it is being removed from it.
    is_attached: bool
    is_leaving: bool

    @cached_property
    def _core_subscriptions(self) -> set[Subscription]:
        return set()

    @cached_property
    def _observations(self) -> dict[CoreEventStream, tuple[Subscription, ...]]:
        """The streams this view observes, with the subscription per consumed event type."""
        return {}

    def observe_core_callback(self, stream: CoreEventStream,
                              event_type: type[CoreEvent], callback: Callable[[CoreEvent], object], *,
                              factory: Callable[..., Subscription] = CallbackSubscription) -> Subscription:
        """An original deferred operation receives relief inside its native loop."""
        subscription = stream.subscribe(
            event_type, self.post_core_callback, factory=partial(factory, callback=callback))
        self._core_subscriptions.add(subscription)
        return subscription

    def retire_core(self, subscription: Subscription) -> None:
        subscription.close()
        self._core_subscriptions.discard(subscription)

    def retire_core_observations(self, stream: CoreEventStream) -> None:
        for subscription in self._observations.pop(stream, ()):
            subscription.close()
        for subscription in tuple(self._core_subscriptions):
            if subscription.stream is stream:
                self.retire_core(subscription)

    def close_core_events(self) -> None:
        """End this view's subscriptions before its logical source disappears."""
        for subscriptions in self._observations.values():
            for subscription in subscriptions:
                subscription.close()
        self._observations.clear()
        for subscription in self._core_subscriptions:
            subscription.close()
        self._core_subscriptions.clear()

    def post_core_callback(self, event: CoreEvent, subscription: CallbackSubscription) -> bool:
        """Deliver one callback event into the native loop."""
        raise NotImplementedError

    async def consume_handlers(self, event, handlers, *args, **kwargs):
        """Run the handlers for one delivered event, in the native loop."""
        raise NotImplementedError


class CoreObserverDispatch(CoreObserver, MroDispatch):
    """A `CoreObserver` whose handlers are declared through `@handles` and dispatched by MRO.

    The shared dispatch chassis both the Textual `CoreEventReceiver` and the Qt
    `QtCoreObserver` inherit: no DOMNode, no Qt base, so consumers on either side get
    `@handles(CoreEvent)`-style declarations, the per-class handler registry, and
    `consumed_core_events()` without a toolkit base in the MRO. Delivery into the native
    loop stays per-side (`post_core_callback`, and Textual's `consume_handlers` override).
    """

    @classmethod
    @cache
    def consumed_core_events(cls) -> tuple[type[CoreEvent], ...]:
        """The Core events this receiver declares a handler for: an observed stream sends it
        only these. The declarations are decoded once per class (a handler may also name a
        non-Core value)."""
        return tuple(dict.fromkeys(event for _name, classes in cls._handler_declarations
                                   for event in classes if issubclass(event, CoreEvent)))

    async def consume_handlers(self, event, handlers, *args, **kwargs):
        """Default handler loop: each handler is called with the event. Sync or async both
        work; Textual's override replaces this with its callback-aware `invoke`."""
        for handler in handlers:
            result = handler(event, *args, **kwargs)
            if inspect.isawaitable(result):
                await result
        return event


class SidebarSubscriber[Source, Failure]:
    """A sidebar view accepts a source, its opening failure and later row changes.

    A plain parent: native widgets bring their own toolkit metaclass, which ABCMeta
    would conflict with.
    """

    def bind_observation(self, observed: Source) -> None:
        raise NotImplementedError

    def bind_failed_observation(self, observed: Failure) -> None:
        raise NotImplementedError

    def present(self, **changes: object) -> None:
        raise NotImplementedError

    def shows_sidebar(self) -> bool:
        """Whether this view shows the sidebar's rows now; a view that is always on screen
        always does."""
        return True


class NotificationSubscriber:
    """A message view receives notification outcomes for its current read scope."""

    def notifications_observed(
        self,
        outcomes: Mapping[tuple[int, str], tuple[MessageNotification, ...]],
    ) -> None:
        raise NotImplementedError

    def notifications_failed(self, error: Exception) -> None:
        raise NotImplementedError

    def notifications_reload(self) -> None:
        raise NotImplementedError
