"""Callbacks implemented by native views that subscribe to Core observations."""

from collections.abc import Callable, Mapping

from agent_comms.messaging.message_notification import MessageNotification

from toad.core.events import CoreEvent, CoreEventStream, Subscription


class CoreObserver:
    """A native view that holds Core event subscriptions for as long as it is shown."""

    def observe_core_callback(self, stream: CoreEventStream, event_type: type[CoreEvent],
                              callback: Callable[[CoreEvent], object], *,
                              factory: Callable[..., Subscription] = Subscription) -> Subscription:
        raise NotImplementedError

    def retire_core(self, subscription: Subscription) -> None:
        raise NotImplementedError


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
