"""A mounted sender refuses a stale destination before entering the write worker."""

from unittest.mock import patch

from toad.widgets.comms_chat import CommsChatView


async def test_a_view_that_changed_during_send_preflight_keeps_the_draft_editable(workspace):
    workspace.thread("peer", "team")
    workspace.comms.messaging.send("peer", "#team", "CURRENT_HISTORY")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("CURRENT_HISTORY")
        view = ui.app.selected_session.query_one(CommsChatView)
        messaging = view.message_history.page_source.loader.comms.messaging
        with patch.object(messaging, "send_user_message", wraps=messaging.send_user_message) as sender:
            await view.deliver_user_message(workspace.roots.wire, "#team", "STALE_DRAFT",
                                            lambda: False, view._show_sent)
            assert sender.call_count == 0
            assert not view.send_block_reason
            assert view.prompt.text == "STALE_DRAFT"
            assert not view.prompt.prompt_text_area.disabled
