"""A mounted sender refuses a stale destination before entering the write worker."""


from agent_comms.launch_root import LaunchRoot

from support.roots import installed_wire
from toad.core.input_events import UserInputSubmitted
from toad.widgets.comms_chat import CommsChatView


async def test_a_view_that_changed_during_send_preflight_keeps_the_draft_editable(workspace):
    workspace.thread("peer", "team")
    workspace.comms.messaging.send("peer", "#team", "CURRENT_HISTORY")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("CURRENT_HISTORY")
        view = ui.app.selected_session.query_one(CommsChatView)
        messaging = view.message_history.page_source.loader.comms.messaging
        before = messaging.bus.bus.revision()
        await view.submit_comms_message(workspace.roots.wire, view.conversation, "STALE_DRAFT",
                                       lambda: False, view._show_sent)
        await ui.until(lambda: not view.prompt.prompt_text_area.disabled,
                       why="the refused draft editable again")
        assert not view.send_block_reason
        assert view.prompt.text == "STALE_DRAFT"
        assert not view.prompt.prompt_text_area.disabled
        assert messaging.bus.bus.revision() == before


async def test_a_route_change_during_service_acquisition_restores_the_draft(workspace):
    workspace.thread("peer", "team")
    second = installed_wire(workspace.roots.attempt / "second")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        view = ui.app.selected_session.query_one(CommsChatView)
        first = view.message_history.page_source.loader.comms
        before = first.bus.bus.revision(), second.bus.bus.revision()
        with LaunchRoot.from_path(second.root).selected():
            await view.submit_input(UserInputSubmitted("SERVICE_ROUTE_REFUSED"))
        await ui.until(lambda: view.prompt.text == "SERVICE_ROUTE_REFUSED"
                       and not view.prompt.prompt_text_area.disabled,
                       why="the service-refused draft to be editable")
        assert not view.send_block_reason
        assert (first.bus.bus.revision(), second.bus.bus.revision()) == before
        assert ui.failure() is None
