"""Textual-facing: an interrupted send from a mounted chat view is never replayable (composer widget state and status)."""

import asyncio
import threading
from unittest.mock import patch
import pytest

from agent_comms.comms import wire


@pytest.fixture
def conversation(workspace):
    workspace.thread("peer", "team")
    workspace.comms.messaging.send("peer", "#team", "INITIAL")
    return workspace


def on_wire(root, body):
    bus = wire(root).bus.bus
    return [row for row in bus.since(0, bus.revision()) if row.body == body]


def times_on_wire(root, body):
    return len(on_wire(root, body))


async def test_a_direct_message_interrupted_while_its_worker_survives_is_not_replayed(conversation):
    from toad.core import input_events
    from toad.widgets.comms_chat import CommsChatView

    root = conversation.roots.wire

    async with conversation.app(size=(105, 32)) as ui:
        await ui.open_direct("peer", actor=conversation.viewer)
        view = ui.textual[0].screen.query_one(CommsChatView)
        messaging = view.message_history.page_source.loader.comms.messaging
        original_send = messaging.send_user_message
        started, release, settled = threading.Event(), threading.Event(), threading.Event()
        calls = 0

        def delayed_send(*args, **kwargs):
            nonlocal calls
            calls += 1
            started.set()
            try:
                if not release.wait(8):
                    raise TimeoutError("send worker was not released")
                return original_send(*args, **kwargs)
            finally:
                settled.set()

        with patch.object(messaging, "send_user_message", delayed_send):
            event = input_events.UserInputSubmitted("CANCELLED-IN-FLIGHT")
            task = asyncio.create_task(view.submit_input(event))
            assert await asyncio.to_thread(started.wait, 8)
            task.cancel()
            await task
            assert view.send_block_reason
            assert view.prompt.text == event.body
            assert view.prompt.prompt_text_area.disabled
            await view.submit_input(event)
            assert calls == 1
            release.set()
            assert await asyncio.to_thread(settled.wait, 8)
            await ui.step()
            await view.submit_input(event)
            assert calls == 1
            assert times_on_wire(root, event.body) == 1


async def test_a_committed_channel_send_keeps_its_identity_and_cannot_be_resent_until_it_is_drawn(
        conversation):
    from toad.core import input_events
    from toad.widgets.comms_chat import CommsChatView
    from toad.wire_history import WireSource

    root = conversation.roots.wire

    async with conversation.app(size=(105, 32)) as ui:
        await ui.open_channel("#team", actor=conversation.viewer)
        channel = ui.textual[0].screen.query_one(CommsChatView)
        await ui.until_shows("INITIAL")
        release = threading.Event()
        real_read = WireSource.read

        def held_read(source, request, through):
            assert release.wait(8), "the held read was not released"
            return real_read(source, request, through)

        messaging = channel.message_history.page_source.loader.comms.messaging
        with (patch.object(WireSource, "read", held_read),
              patch.object(messaging, "send_user_message", wraps=messaging.send_user_message) as sender):
            channel.prompt.text = "DIFFERENT_UNSENT_DRAFT"
            sent = input_events.UserInputSubmitted("COMMITTED-NOT-DRAWN")
            await channel.submit_input(sent)
            rows = on_wire(root, sent.body)
            assert len(rows) == 1 and sender.call_count == 1
            await ui.until(lambda: rows[0].message_id in channel.status,
                           why="the undrawn send's exact record in its visible status")
            # The sent record owns the hold; a different draft remains untouched.
            assert channel.send_block_reason
            assert channel.prompt.text == "DIFFERENT_UNSENT_DRAFT"
            assert channel.prompt.prompt_text_area.disabled
            assert str(rows[0].seq) in channel.status
            assert rows[0].message_id in channel.status
            await channel.submit_input(sent)
            assert sender.call_count == 1
            release.set()
            await ui.until(lambda: not channel.send_block_reason, why="the sent message drawn")
            assert ui.shows(sent.body)
            assert channel.prompt.text == "DIFFERENT_UNSENT_DRAFT" and not channel.prompt.prompt_text_area.disabled


async def test_a_send_whose_completion_fails_after_commit_shows_the_committed_record_and_is_not_resent(
        conversation):
    from agent_comms.errors import CommittedMessageError
    from toad.core import input_events
    from toad.widgets.comms_chat import CommsChatView
    from toad.wire_history import WireSource

    root = conversation.roots.wire

    async with conversation.app(size=(105, 32)) as ui:
        await ui.open_channel("#team", actor=conversation.viewer)
        channel = ui.textual[0].screen.query_one(CommsChatView)
        await ui.until_shows("INITIAL")
        release = threading.Event()
        real_read = WireSource.read
        messaging = channel.message_history.page_source.loader.comms.messaging
        original_send = messaging.send_user_message
        committed = []

        def held_read(source, request, through):
            assert release.wait(8), "the held read was not released"
            return real_read(source, request, through)

        def commit_then_fail(*args, **kwargs):
            committed.append(original_send(*args, **kwargs))
            raise CommittedMessageError(committed[-1])

        with (patch.object(WireSource, "read", held_read),
              patch.object(messaging, "send_user_message", side_effect=commit_then_fail) as sender):
            channel.prompt.text = "DIFFERENT_UNSENT_DRAFT"
            sent = input_events.UserInputSubmitted("COMMITTED-THEN-FAILED")
            await channel.submit_input(sent)
            [record] = committed
            await ui.until(lambda: record.message_id in channel.status,
                           why="the committed record in its visible status after completion failed")
            assert times_on_wire(root, sent.body) == 1 and sender.call_count == 1
            # The exact committed record owns the status; nothing claims the message was not sent.
            assert channel.send_block_reason == f"Sent {root}/{record.seq}/{record.message_id}; waiting to be drawn, do not retry"
            assert channel.prompt.text == "DIFFERENT_UNSENT_DRAFT"
            assert channel.prompt.prompt_text_area.disabled
            await channel.submit_input(sent)
            assert sender.call_count == 1
            release.set()
            await ui.until(lambda: not channel.send_block_reason, why="the committed message drawn")
            assert ui.shows(sent.body)
            assert times_on_wire(root, sent.body) == 1
            assert channel.prompt.text == "DIFFERENT_UNSENT_DRAFT"
