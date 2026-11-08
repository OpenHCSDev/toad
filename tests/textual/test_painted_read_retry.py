"""A painted message must remain acknowledgeable after its original proof expires."""

import asyncio

from agent_comms.read_basis import ChannelConversation
from toad.widgets.comms_chat import CommsChatView
from toad.wire_history import WirePageBuffer


async def test_painted_read_recovers_when_scope_changes_before_ack(workspace, monkeypatch):
    for name, tags in (("alice", ("team",)), ("carol", ()), ("dave", ())):
        workspace.thread(name, *tags, running=True)
    comms = workspace.comms
    viewer = workspace.viewer
    comms.messaging.send("carol", "dave", "older newly visible DM")
    message = comms.messaging.send("alice", "#team", "painted before scope change").message
    comms.channels.set_channel_any_mode("#team", True)
    reached, release = asyncio.Event(), asyncio.Event()
    original = WirePageBuffer.mark_page
    attempts = []

    async def delayed(source, page):
        attempts.append(page)
        if not reached.is_set():
            reached.set()
            await release.wait()
        await original(source, page)

    monkeypatch.setattr(WirePageBuffer, "mark_page", delayed)
    async with workspace.app(size=(100, 30)) as ui:
        await ui.open_channel("#team", actor=viewer)
        await ui.until(reached.is_set, why="the real painted read to reach its acknowledgement")
        history = ui.textual[0].screen.query_one(CommsChatView).message_history
        source = history.page_source
        await ui.app.coordination_access.stop_observing()
        comms.channels.update_tags("carol", add=frozenset({"team"}))
        release.set()
        snapshot = comms.registry.snapshot()
        channel = ChannelConversation("#team")
        try:
            async with asyncio.timeout(6):
                await ui.until(
                    lambda: message.seq in comms.bus.reads.cursor(viewer, snapshot).for_conversation(channel),
                    why="the actually painted message to be acknowledged with fresh evidence",
                )
        except TimeoutError:
            raise AssertionError(
                f"painted message remains unread: attempts={len(attempts)}, "
                f"all_same_proof={all(page == attempts[0] for page in attempts)}, "
                f"source_replaced={history.page_source is not source}, "
                f"source_ready={history.source_ready}, "
                f"pending_painted={len(history.read_fragments())}"
            ) from None
        assert len(attempts) >= 2
        assert sum(page == attempts[0] for page in attempts) == 1, "A refused proof is never submitted again"
