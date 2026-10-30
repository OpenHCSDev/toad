"""A real shared observer updates a shown channel and leaves its parked view alone."""

async def test_live_update_paints_parked_channel_reads_nothing_and_return_shows_the_update(workspace):
    from toad.widgets.comms_chat import CommsChatView, session_thread_name

    comms = workspace.comms
    for name in ("sender", "reader", session_thread_name(workspace.project)):
        workspace.thread(name, "alpha")
    initial = comms.messaging.send("sender", "#alpha", "INITIAL ROW").message
    async with workspace.app(size=(113, 34)) as ui:
        app = ui.textual[0]
        access = app.coordination_access
        owner = ui.selected_tab
        mode = await ui.open_channel("#alpha", actor="reader")
        chat = app.selected_session.query_one(CommsChatView)
        await ui.until_shows("INITIAL ROW")
        await chat.message_history.toggle_style()
        await ui.until(
            lambda: any(initial.reference in read.references for read in access.notification_interest.reads),
            why="the shown channel to subscribe to its notification references",
        )

        comms.messaging.send("sender", "#alpha", "LIVE UPDATE")
        await ui.until_shows("LIVE UPDATE")

        await ui.select_tab(owner)
        await ui.until(lambda: not access.notification_interest.reads, why="the parked channel to unsubscribe")
        comms.messaging.send("sender", "#alpha", "PARKED UPDATE")
        await ui.step(1.2)
        assert not access.notification_views and not access.notification_interest.reads
        await ui.select_tab(mode)
        await ui.until_shows("PARKED UPDATE")
        await ui.until(lambda: bool(access.notification_interest.reads), why="the returned channel to resubscribe")
        assert app.selected_session.query_one(CommsChatView) is chat
