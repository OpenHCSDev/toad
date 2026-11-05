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
            lambda: any(initial.reference in read.operation.references for read in access.notification_interest.reads),
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


async def test_every_message_sent_while_parked_paints_on_return(workspace):
    """A parked channel that misses a run of messages shows all of them on return.

    The reported behaviour is that a tab left unvisited shows only the last of the
    messages that arrived, and the rest appear later in one burst. The single
    parked update above passes; this sends a run while the channel is parked and
    requires every one of them to be painted when the reader comes back.
    """
    from toad.widgets.comms_chat import CommsChatView, session_thread_name

    comms = workspace.comms
    for name in ("sender", "reader", session_thread_name(workspace.project)):
        workspace.thread(name, "alpha")
    comms.messaging.send("sender", "#alpha", "INITIAL ROW")
    parked = [f"PARKED UPDATE {index:02d}" for index in range(4)]
    async with workspace.app(size=(113, 34)) as ui:
        app = ui.textual[0]
        access = app.coordination_access
        owner = ui.selected_tab
        mode = await ui.open_channel("#alpha", actor="reader")
        await ui.until_shows("INITIAL ROW")

        await ui.select_tab(owner)
        await ui.until(lambda: not access.notification_interest.reads,
                       why="the parked channel to unsubscribe")
        for body in parked:
            comms.messaging.send("sender", "#alpha", body)
        await ui.step(1.2)

        await ui.select_tab(mode)
        for body in parked:
            await ui.until_shows(body)
        assert app.selected_session.query_one(CommsChatView) is not None
