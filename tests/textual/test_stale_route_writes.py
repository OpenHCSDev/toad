"""A mounted sender refuses a stale destination before entering the write worker."""


from toad.bus_submission import BusDestination
from toad.conversation_submission import OrdinaryInputSubmission
from toad.widgets.comms_chat import CommsChatView


async def test_a_view_that_changed_before_its_send_left_keeps_the_draft_editable(workspace):
    workspace.thread("peer", "team")
    workspace.comms.messaging.send("peer", "#team", "CURRENT_HISTORY")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("CURRENT_HISTORY")
        view = ui.app.selected_session.query_one(CommsChatView)
        messaging = workspace.comms.messaging
        before = messaging.bus.bus.revision()
        stale = BusDestination(workspace.roots.wire, view.conversation, lambda: False, view.show_sent)
        await view.submissions.start_bus(OrdinaryInputSubmission("STALE_DRAFT"), stale).prepare()
        await ui.until(lambda: view.prompt.text == "STALE_DRAFT", why="the refused draft back in the composer")
        assert not view.submissions.delivering
        assert not view.prompt.prompt_text_area.disabled
        assert messaging.bus.bus.revision() == before
