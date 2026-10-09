import asyncio
import gc
from weakref import ref

import pytest

from textual.app import App, ComposeResult
from textual.reactive import var
from textual.widgets import Button, Footer, Input, Label


class Publisher(Label):
    value = var("quiet")


class Subscriber(Label):
    def receive(self, value):
        self.update(value)


def make_callback(node):
    return lambda value: node.update(value)


@pytest.mark.parametrize("closure", [False, True])
async def test_quiet_reactive_publisher_releases_removed_subscriber(closure):
    app = App()
    async with app.run_test() as pilot:
        publisher = Publisher()
        subscriber = Subscriber("subscriber")
        await app.mount(publisher, subscriber)
        callback = make_callback(subscriber) if closure else subscriber.receive
        subscriber.watch(publisher, "value", callback, init=False)
        retained = ref(subscriber)
        del callback
        await subscriber.remove()
        await pilot.pause()
        assert not getattr(publisher, "__watchers", {}).get("value"), "Quiet publisher retains closed subscriber"
        del subscriber
        gc.collect()
        assert retained() is None


async def test_cancelled_subscriber_unregisters_without_affecting_live_watches():
    app = App()
    async with app.run_test() as pilot:
        publisher, first, second = Publisher(), Subscriber(), Subscriber()
        await app.mount(publisher, first, second)
        first.watch(publisher, "value", first.receive, init=False)
        second.watch(publisher, "value", second.receive, init=False)
        task = first._task
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert [node for node, _ in getattr(publisher, "__watchers")["value"]] == [second]
        publisher.value = "changed"
        await pilot.pause()
        assert second.content == "changed"


async def test_reverse_reactive_ownership_does_not_retain_publisher():
    app = App()
    async with app.run_test() as pilot:
        publisher, subscriber = Publisher(), Label()
        await app.mount(publisher, subscriber)
        subscriber.watch(publisher, "value", subscriber.update, init=False)
        retained = ref(publisher)
        await publisher.remove()
        del publisher
        await pilot.pause()
        gc.collect()
        assert retained() is None


class FooterApp(App):
    BINDINGS = [("f7", "noop", "Fixture action")]

    def action_noop(self):
        pass

    def compose(self) -> ComposeResult:
        yield Input(id="input")
        yield Button("button", id="button")
        yield Footer()


async def test_footer_binding_churn_does_not_retain_retired_keys():
    app = FooterApp()
    async with app.run_test() as pilot:
        footer = app.screen.query_one(Footer)
        for _ in range(5):
            app.screen.query_one(Input).focus()
            await pilot.pause()
            app.screen.query_one(Button).focus()
            await pilot.pause()
        watchers = getattr(footer, "__watchers", {}).get("compact", [])
        assert watchers, "Fixture needs data-bound footer keys"
        closed = [type(node).__name__ for node, _ in watchers if node._closed]
        assert not closed, f"Footer.compact retained {len(closed)} closed keys"
