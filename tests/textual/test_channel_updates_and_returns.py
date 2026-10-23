"""A real shared observer updates a shown channel and leaves its parked view alone."""

import os
from unittest.mock import patch


async def test_live_update_paints_parked_channel_unsubscribes_and_return_shows_the_update(workspace):
    from toad.widgets.comms_chat import CommsChatView, session_thread_name

    comms = workspace.comms
    for name in ("sender", "reader", session_thread_name(workspace.project)):
        workspace.thread(name, "alpha")
    comms.messaging.send("sender", "#alpha", "INITIAL ROW")
    async with workspace.app(size=(113, 34)) as ui:
        app = ui.app
        owner = ui.selected_tab
        mode = await ui.open_channel("#alpha", actor="reader")
        chat = app.selected_session.query_one(CommsChatView)
        await ui.until_shows("INITIAL ROW")
        await chat.message_history.toggle_style()
        feedback = chat.message_history.notification_view
        access = app.coordination_access
        await ui.until(lambda: feedback in access.notification_views,
                       why="the channel's notification subscription")
        assert access.observation.observed().process.process.pid != os.getpid()
        arrivals = []
        publish = feedback.notifications_observed

        def received(results):
            arrivals.append(results)
            publish(results)

        with patch.object(feedback, "notifications_observed", received):
            comms.messaging.send("sender", "#alpha", "LIVE UPDATE")
            await ui.until_shows("LIVE UPDATE")
            await ui.until(lambda: bool(arrivals), why="the shared observer's notification reply")
            await ui.select_tab(owner)
            assert feedback not in access.notification_views
            parked = len(arrivals)
            comms.messaging.send("sender", "#alpha", "PARKED UPDATE")
            await ui.step(1.2)
            assert len(arrivals) == parked, "a parked channel received notification bodies"
            assert feedback not in access.notification_views
            await ui.select_tab(mode)
            await ui.until_shows("PARKED UPDATE")
            await ui.until(lambda: feedback in access.notification_views,
                           why="the returned channel's notification subscription")
            assert app.selected_session.query_one(CommsChatView) is chat
