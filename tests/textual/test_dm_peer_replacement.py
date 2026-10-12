"""Textual-facing: a mounted direct-message view (its rows and read-mark worker) cannot mark a replacement peer it never painted."""

import asyncio
from threading import Event
from unittest.mock import patch

from agent_comms.history_views import HistoryViews


async def test_a_page_painted_for_the_old_peer_does_not_mark_the_replacement_peer_read(workspace):
    from toad.widgets.comms_chat import CommsChatView

    workspace.thread("peer", running=True)
    comms = workspace.comms
    viewer = workspace.viewer
    comms.messaging.send("peer", viewer, "old peer painted")
    entered, release = Event(), Event()
    original_mark = HistoryViews.mark_dm_view_read

    def pause_old_mark(self, peer, **kwargs):
        entered.set()
        if not release.wait(8):
            raise TimeoutError("Old painted marker was not released")
        return original_mark(self, peer, **kwargs)

    try:
        with patch.object(HistoryViews, "mark_dm_view_read", pause_old_mark):
            async with workspace.app(size=(120, 40)) as ui:
                owner = ui.selected_tab
                await ui.open_direct("peer", actor=viewer)
                chat = ui.textual[0].screen.query_one(CommsChatView)
                assert await asyncio.to_thread(entered.wait, 4)
                assert [message.body for message in chat.message_history.messages] == ["old peer painted"]
                assert comms.bus.pending_count(viewer, "peer") == 1

                comms.registry.unregister("peer")
                comms.registry.remove("peer")
                workspace.thread("peer", running=True)
                comms.messaging.send("peer", viewer, "new peer never painted")
                await ui.select_tab(owner)
                release.set()
                await ui.until(lambda: not chat.message_history.marking, why="the held mark to finish")
                assert comms.bus.pending_count(viewer, "peer") == 1
                assert not any(message.body == "new peer never painted" for message in chat.message_history.messages)
    finally:
        release.set()
