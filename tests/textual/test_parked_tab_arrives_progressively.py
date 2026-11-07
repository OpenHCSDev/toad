"""A tab that missed a run of messages should have them when the reader returns."""


def loaded(chat) -> tuple[int, int]:
    history = chat.message_history
    return len(history.pages), sum(len(page.prepared.fragments) for page in history.pages)


async def test_control_a_visible_channel_loads_the_messages(workspace):
    """Control: the same send/look sequence with the tab left visible."""
    from toad.widgets.comms_chat import CommsChatView, session_thread_name

    comms = workspace.comms
    for name in ("sender", "reader", session_thread_name(workspace.project)):
        workspace.thread(name, "alpha")
    comms.messaging.send("sender", "#alpha", "INITIAL ROW")
    missed = [f"PARKED UPDATE {index:02d}" for index in range(6)]
    async with workspace.app(size=(113, 34)) as ui:
        app = ui.textual[0]
        await ui.open_channel("#alpha", actor="reader")
        chat = app.selected_session.query_one(CommsChatView)
        await ui.until_shows("INITIAL ROW")
        before = loaded(chat)
        for body in missed:
            comms.messaging.send("sender", "#alpha", body)
        await ui.until(lambda: loaded(chat)[1] >= before[1] + len(missed),
                       why=f"the visible channel to load {len(missed)} new messages")


async def test_a_parked_tab_loads_the_backlog_while_it_is_parked(workspace):
    from toad.widgets.comms_chat import CommsChatView, session_thread_name

    comms = workspace.comms
    for name in ("sender", "reader", session_thread_name(workspace.project)):
        workspace.thread(name, "alpha")
    comms.messaging.send("sender", "#alpha", "INITIAL ROW")
    missed = [f"PARKED UPDATE {index:02d}" for index in range(6)]
    async with workspace.app(size=(113, 34)) as ui:
        app = ui.textual[0]
        access = app.coordination_access
        owner = ui.selected_tab
        mode = await ui.open_channel("#alpha", actor="reader")
        chat = app.selected_session.query_one(CommsChatView)
        await ui.until_shows("INITIAL ROW")
        await ui.select_tab(owner)
        await ui.until(lambda: not access.notification_interest.reads, why="park")
        before = loaded(chat)
        for body in missed:
            comms.messaging.send("sender", "#alpha", body)
        # Waited for before the tab is selected again: the backlog loads while it is parked,
        # not as a burst on return.
        await ui.until(lambda: loaded(chat)[1] >= before[1] + len(missed),
                       why=f"the parked tab to load {len(missed)} missed messages while away")
        await ui.select_tab(mode)
