"""Textual-facing: a shown channel view paints live updates; a parked one reads nothing and shows its update on return (same widget)."""

import sys
import threading

from agent_comms.history_views import HistoryViews


async def test_live_update_paints_parked_channel_reads_nothing_and_return_shows_the_update(workspace):
    from toad.widgets.comms_chat import CommsChatView, session_thread_name

    comms = workspace.comms
    for name in ("sender", "reader", session_thread_name(workspace.project)):
        workspace.thread(name, "alpha")
    comms.messaging.initialize_private_initial_protocol()
    comms.messaging.send("sender", "#alpha", "INITIAL ROW")
    reads = []
    code = HistoryViews.message_notifications_for_references.__code__

    def observe(frame, event, argument):
        if event == "call" and frame.f_code is code:
            reads.append(1)

    old_profile, old_thread_profile = sys.getprofile(), threading.getprofile()
    sys.setprofile(observe)
    threading.setprofile(observe)
    try:
        async with workspace.app(size=(113, 34)) as ui:
            app = ui.textual[0]
            owner = ui.selected_tab
            mode = await ui.open_channel("#alpha", actor="reader")
            chat = app.selected_session.query_one(CommsChatView)
            await ui.until_shows("INITIAL ROW")
            await chat.message_history.toggle_style()
            await ui.until(lambda: bool(reads), why="the first notification read")

            comms.messaging.send("sender", "#alpha", "LIVE UPDATE")
            await ui.until_shows("LIVE UPDATE")

            await ui.select_tab(owner)
            parked = len(reads)
            comms.messaging.send("sender", "#alpha", "PARKED UPDATE")
            await ui.step(1.2)
            assert len(reads) == parked, "a parked channel read notification bodies"
            await ui.select_tab(mode)
            await ui.until_shows("PARKED UPDATE")
            assert app.selected_session.query_one(CommsChatView) is chat
    finally:
        sys.setprofile(old_profile)
        threading.setprofile(old_thread_profile)
