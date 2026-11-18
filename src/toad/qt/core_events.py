"""Core events delivered on Qt's loop: the shared observer keeps the subscriptions, and the
view's own QtDeliveryReceiver consumes each callback on its thread, in arrival order."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from formbridge.publications import Subscription
from pyqt_reactive.services.publication_delivery import QtDeliveryReceiver

from toad.app_node import AppScoped
from toad.client.subscribers import CallbackSubscription, CoreObserverDispatch
from toad.core.events import CoreEvent, Publication


@dataclass(frozen=True)
class QtPublication(Publication):
    """One Core event delivered to a Qt view, with the subscription it arrived on."""

    event: CoreEvent
    subscription: Subscription


class QtCoreObserver(QtDeliveryReceiver, CoreObserverDispatch, AppScoped):
    """A Qt view's Core subscriptions, each callback consumed after the one before it.

    The handler dispatch chassis (``@handles``, ``consumed_core_events``, the default
    ``consume_handlers`` loop) comes from the shared `CoreObserverDispatch`; delivery
    into Qt's loop stays here through `QtDeliveryReceiver.deliver`. `AppScoped` declares
    ``self.app: ToadApp`` so every Qt widget inheriting `QtCoreObserver` (`PeerActivity`,
    `QtGoalBar`, ...) carries the same application-refinement type ``ToadNode`` gives
    Textual widgets, without re-declaring it per subclass.
    """

    def post_core_callback(self, event: CoreEvent, subscription: CallbackSubscription) -> bool:
        self.deliver(partial(subscription.consume, self, QtPublication(event, subscription)))
        return True

    def delivery_failed(self, error: Exception) -> None:
        self.app.report_fatal(error)

    def close_core_events(self) -> None:
        super().close_core_events()
        self.close_deliveries()
