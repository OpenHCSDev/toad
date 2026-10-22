"""Textual-facing: the saved-session viewer subscribes to its selected archive and retires that subscription on selection and close."""

from agent_comms.comms import Comms
from agent_comms.ui_model.observation import ReadRecordedNotifications
from textual.widgets import Select

from support.routes import private_root
from toad.screens.historical_sessions import HistoricalSessions, RecordedContents


async def test_historical_notifications_follow_the_mounted_selection_and_close(workspace):
    live = workspace.comms
    workspace.thread("peer", "team")
    workspace.thread("sender", "team")
    live.messaging.send("sender", "peer", "THE LIVE CONVERSATION")
    archives = []
    for label in ("FIRST", "SECOND"):
        root, _ = private_root(
            workspace.roots.attempt / label.lower(), workspace.project, "archive seed"
        )
        archive = Comms(root)
        message = archive.messaging.send("owner", "peer", f"ARCHIVED {label}").message
        source = live.views.attach_history(root)
        request = ReadRecordedNotifications(
            str(live.root), (message.reference,), source=source.key
        )
        expected = request.read(live)
        assert expected, "The archived message must retain its notification result"
        archives.append((source, message, expected))

    async with workspace.app(size=(120, 40)) as ui:
        app, _ = ui.textual
        await ui.open_direct("peer", actor=workspace.viewer)
        chat = ui.conversation
        await ui.until_shows("THE LIVE CONVERSATION")
        await ui.press("f8")
        await ui.until(
            lambda: isinstance(app.screen, HistoricalSessions),
            why="the saved-session viewer",
        )
        viewer = app.screen
        access = app.coordination_access
        selector = viewer.query_one("#saved-identity", Select)
        previous = None
        for source, message, expected in archives:
            selector.value = next(
                index for index, item in enumerate(viewer.threads)
                if item.source.key == source.key and item.thread.name == "peer"
            )
            await ui.until_shows(message.body)
            await ui.until(
                lambda: any(
                    isinstance(read, ReadRecordedNotifications)
                    and read.source == source.key
                    and message.reference in read.references
                    for read in access.notification_interest.reads
                ),
                why="the visible archive's notification subscription",
            )
            request = next(
                read for read in access.notification_interest.reads
                if isinstance(read, ReadRecordedNotifications)
                and read.source == source.key and message.reference in read.references
            )
            await ui.until(
                lambda: expected.keys()
                <= access.notification_outcomes.get(request, {}).keys(),
                why="the selected archive's notification answer",
            )
            assert all(
                access.notification_outcomes[request][reference] == state
                for reference, state in expected.items()
            )
            if previous is not None:
                assert not previous.is_attached
                assert previous not in access.notification_views
            previous = viewer.query_one("#saved-content", RecordedContents)

        await ui.press("escape")
        await ui.until(lambda: app.screen is not viewer, why="the saved viewer to close")
        await ui.until(
            lambda: not any(
                isinstance(read, ReadRecordedNotifications)
                for read in access.notification_interest.reads
            ),
            why="the closed viewer to retire its archive subscriptions",
        )
        assert previous not in access.notification_views
        assert ui.conversation is chat
        await ui.until_shows("THE LIVE CONVERSATION")
        assert not ui.shows("ARCHIVED FIRST") and not ui.shows("ARCHIVED SECOND")
