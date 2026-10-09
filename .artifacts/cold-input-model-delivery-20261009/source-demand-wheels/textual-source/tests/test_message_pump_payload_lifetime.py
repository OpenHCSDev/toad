import asyncio
import gc
from weakref import ref

import pytest

from textual.app import App, ComposeResult
from textual.message import Message
from textual.widget import Widget


class Payload:
    pass


class PayloadMessage(Message):
    def __init__(self, payload: Payload) -> None:
        super().__init__()
        self.payload = payload


class Receiver(Widget):
    def __init__(self) -> None:
        super().__init__()
        self.received = asyncio.Event()

    def on_payload_message(self, message: PayloadMessage) -> None:
        message.stop()
        self.received.set()


class PayloadApp(App):
    def compose(self) -> ComposeResult:
        yield Receiver()


@pytest.mark.asyncio
async def test_idle_pump_releases_processed_payload() -> None:
    async with PayloadApp().run_test() as pilot:
        await pilot.pause()
        receiver = pilot.app.query_one(Receiver)
        payload = Payload()
        retained = ref(payload)
        receiver.post_message(PayloadMessage(payload))
        del payload
        await receiver.received.wait()
        # Pilot.pause posts a synchronization callback to every pump, which
        # would replace the last message and mask idle payload retention.
        await asyncio.sleep(0)
        gc.collect()
        assert retained() is None


@pytest.mark.asyncio
async def test_message_signal_allocated_only_when_used() -> None:
    async with PayloadApp().run_test() as pilot:
        receiver = pilot.app.query_one(Receiver)
        receiver.post_message(PayloadMessage(Payload()))
        await receiver.received.wait()
        await pilot.pause()
        assert "message_signal" not in receiver.__dict__

        delivered: list[Payload] = []

        def observe(message: Message) -> None:
            if isinstance(message, PayloadMessage):
                delivered.append(message.payload)

        receiver.message_signal.subscribe(receiver, observe, immediate=True)
        payload = Payload()
        receiver.post_message(PayloadMessage(payload))
        await pilot.pause()
        assert delivered == [payload]
