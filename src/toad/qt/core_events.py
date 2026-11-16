"""Core events delivered on Qt's loop: the shared observer keeps the subscriptions, this
delivers each callback through the host's schedule_ui and runs its handlers."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass

from formbridge.publications import Subscription

from toad.client.subscribers import CallbackSubscription, CoreObserver
from toad.core.events import CoreEvent, Publication


@dataclass(frozen=True)
class QtPublication(Publication):
    """One Core event delivered to a Qt view, with the subscription it arrived on."""

    event: CoreEvent
    subscription: Subscription


class QtCoreObserver(CoreObserver):
    """A Qt view's Core subscriptions, delivered on the next turn of Qt's loop."""

    def post_core_callback(self, event: CoreEvent, subscription: CallbackSubscription) -> bool:
        publication = QtPublication(event, subscription)
        self.coordination.app.schedule_ui(
            lambda: asyncio.ensure_future(subscription.consume(self, publication)))
        return True

    async def consume_handlers(self, event, handlers, *args, **kwargs):
        for handler in handlers:
            result = handler(event, *args, **kwargs)
            if inspect.isawaitable(result):
                await result
        return event
