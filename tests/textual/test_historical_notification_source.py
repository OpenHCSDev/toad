"""The mounted historical screen observes its selected archive and retires its subscription."""

from agent_comms.historical_views import HistoricalThread
from agent_comms.ui_model.observation import ReadRecordedNotifications
from agent_comms.threads import Thread

from support.roots import installed_wire
from toad.screens.historical_sessions import HistoricalSessions, RecordedContents


async def test_historical_notification_keeps_selected_source_and_lifetime(workspace):
    old, live = installed_wire(workspace.roots.attempt / "old"), workspace.comms
    for name in ("sender", "agent"):
        old.registry.declare(Thread(name, frozenset(), str(workspace.project)))
    workspace.thread("agent")
    message = old.messaging.send("sender", "agent", "HISTORICAL_NOTIFICATION").message
    source = live.views.attach_history(old.root)
    item = HistoricalThread(source, source.provenance.require("agent"))

    async with workspace.app() as ui:
        screen = HistoricalSessions(live, (item,))
        await ui.app.push_screen(screen)
        await ui.until(lambda: "HISTORICAL_NOTIFICATION" in ui.painted(screen),
                       why="the selected archive's saved message")
        content = screen.query_one(RecordedContents)
        access = ui.app.coordination_access
        await ui.until(lambda: content in access.notification_views,
                       why="the historical body's notification subscription")
        request = access.notification_views[content]
        assert isinstance(request, ReadRecordedNotifications)
        assert request.source == source.key
        assert request.references == (message.reference,)
        await ui.until(lambda: request in access.notification_outcomes,
                       why="the archive's actual observation reply")
        outcomes = access.notification_outcomes[request]
        assert outcomes[message.seq, message.message_id]

        await screen.dismiss()
        await ui.until(lambda: content not in access.notification_views,
                       why="the closed historical body's subscription to retire")
        assert ui.failure() is None
