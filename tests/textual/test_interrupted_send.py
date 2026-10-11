"""Textual-facing: an interrupted send from a mounted chat view is never replayable (composer widget state and status)."""

import asyncio
import threading
from unittest.mock import patch

from agent_comms.comms import wire

from support.routes import private_root, publish_route, select_root_by_default_route
from support.textual_steps import refresh_chat


def times_on_wire(root, body):
    return [row.body for row in wire(root).bus.log.full_history()].count(body)


async def test_a_direct_message_interrupted_while_its_worker_survives_is_not_replayed(workspace, monkeypatch):
    from toad.core import input_events
    from toad.widgets.comms_chat import CommsChatView

    attempt = workspace.roots.attempt
    home = select_root_by_default_route(monkeypatch, attempt)
    root, root_id = private_root(attempt / "wire-private", workspace.project, "INITIAL")
    publish_route(home, root, root_id)

    async with workspace.app(size=(105, 32)) as ui:
        await ui.open_direct("peer", actor="user")
        view = ui.textual[0].screen.query_one(CommsChatView)
        messaging = view.message_history.reader.comms.messaging
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
            assert view._human_admission_blocked
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


async def test_a_channel_send_cancelled_while_its_committed_message_is_being_painted_keeps_its_identity(
        workspace, monkeypatch):
    from toad.core import input_events
    from toad.widgets.comms_chat import CommsChatView

    attempt = workspace.roots.attempt
    home = select_root_by_default_route(monkeypatch, attempt)
    root, root_id = private_root(attempt / "wire-private", workspace.project, "INITIAL")
    publish_route(home, root, root_id)

    async with workspace.app(size=(105, 32)) as ui:
        await ui.open_channel("#team", actor="user")
        channel = ui.textual[0].screen.query_one(CommsChatView)
        await refresh_chat(channel)
        entered_paint, release_paint = asyncio.Event(), asyncio.Event()
        original_mount = channel.message_history._mount_page

        async def delayed_paint(page, **kwargs):
            if any(message.body == "POSTRECEIPT-CANCEL" for message in page.messages):
                entered_paint.set()
                await release_paint.wait()
            return await original_mount(page, **kwargs)

        messaging = channel.message_history.reader.comms.messaging
        with (patch.object(channel.message_history, "_mount_page", delayed_paint),
              patch.object(messaging, "send_user_message", wraps=messaging.send_user_message) as sender):
            sent = input_events.UserInputSubmitted("POSTRECEIPT-CANCEL")
            pending = asyncio.create_task(channel.submit_input(sent))
            async with asyncio.timeout(8):
                await entered_paint.wait()
            rows = [row for row in wire(root).bus.log.full_history() if row.body == sent.body]
            assert len(rows) == 1 and sender.call_count == 1
            pending.cancel()
            await pending
            assert channel._human_admission_blocked
            assert channel.prompt.text == sent.body
            assert channel.prompt.prompt_text_area.disabled
            assert str(rows[0].seq) in channel.status
            assert rows[0].message_id in channel.status
            await channel.submit_input(sent)
            assert sender.call_count == 1
            release_paint.set()
