"""A mounted sender refuses a stale destination before entering the write worker."""


from toad.widgets.comms_chat import CommsChatView


async def test_a_view_that_changed_during_send_preflight_keeps_the_draft_editable(workspace):
    workspace.thread("peer", "team")
    workspace.comms.messaging.send("peer", "#team", "CURRENT_HISTORY")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("CURRENT_HISTORY")
        view = ui.app.selected_session.query_one(CommsChatView)
        messaging = workspace.comms.messaging
        before = messaging.bus.bus.revision()
        await view.submit_comms_message(workspace.roots.wire, view.conversation, "STALE_DRAFT",
                                       lambda: False, view._show_sent)
        await ui.until(lambda: not view.prompt.prompt_text_area.disabled,
                       why="the refused draft editable again")
        assert not view.send_block_reason
        assert view.prompt.text == "STALE_DRAFT"
        assert not view.prompt.prompt_text_area.disabled
        assert messaging.bus.bus.revision() == before
