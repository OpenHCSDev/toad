"""Core events delivered on Qt's loop: the shared observer keeps the subscriptions, and the
view's own QtDeliveryReceiver consumes each callback on its thread, in arrival order."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import partial

from formbridge.publications import Subscription
from pyqt_reactive.services.publication_delivery import QtDeliveryReceiver

from toad.client.subscribers import CallbackSubscription, CoreReceiver
from toad.core.events import CoreEvent, Publication


@dataclass(frozen=True)
class QtPublication(Publication):
    """One Core event delivered to a Qt view, with the subscription it arrived on."""

    event: CoreEvent
    subscription: Subscription


class QtCoreObserver(QtDeliveryReceiver, CoreReceiver):
    """A Qt view's Core subscriptions, each callback or declared handler consumed after the one
    before it, on the view's own thread."""

    def post_core_callback(self, event: CoreEvent, subscription: CallbackSubscription) -> bool:
        self.deliver(partial(subscription.consume, self, QtPublication(event, subscription)))
        return True

    def post_core_observation(self, event: CoreEvent, subscription: Subscription) -> bool:
        self.deliver(partial(self.consume_publication, QtPublication(event, subscription)))
        return True

    post_core_event = post_core_observation
    """Qt widgets do not bubble: what this view publishes reaches its own handlers, and a
    view that listens to another observes that one's stream."""

    async def consume_publication(self, publication: QtPublication) -> None:
        """A declared handler receives the event, and the publication it came on."""
        if publication.subscription.active:
            await self.consume_handlers(publication.event, self.handlers_for(publication.event), publication)

    def delivery_failed(self, error: Exception) -> None:
        self.coordination.app.report_fatal(error)

    def close_core_events(self) -> None:
        super().close_core_events()
        self.close_deliveries()

    async def consume_handlers(self, event, handlers, *args, **kwargs):
        for handler in handlers:
            result = handler(event, *args, **kwargs)
            if inspect.isawaitable(result):
                await result
        return event
