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
        await ui.step(1.2)
        after = loaded(chat)
        assert after[1] >= before[1] + len(missed), f"visible channel did not load them: {before} -> {after}"


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
        await ui.step(1.2)
        while_parked = loaded(chat)
        await ui.select_tab(mode)
        await ui.step(0.05)
        assert while_parked[1] >= before[1] + len(missed), (
            f"the parked tab loaded {while_parked[1] - before[1]} of {len(missed)} missed items "
            f"while it was away; the rest load on return as a burst"
        )
