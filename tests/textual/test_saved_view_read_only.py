"""Textual-facing: a saved view opens from the sidebar as normal history with a disabled composer (widget state)."""

from agent_comms.catalog_document import CatalogDocument, ChannelPreferences
from agent_comms.channels import ActivityView, AnyOfMatch, ViewPredicate

from support.textual_steps import channel_roster


async def test_saved_view_shows_union_history_keeps_its_pin_and_refuses_to_send(workspace):
    from toad.core import input_events
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.comms_sidebar import ChannelGroup

    workspace.thread(workspace.project.name, running=True)
    workspace.thread("api-agent", "api", running=True)
    workspace.thread("ui-agent", "ui", running=True)
    comms = workspace.comms
    rows = [comms.messaging.send_message("api-agent", target, body)
            for target, body in (("#engineering", "union message"), ("#api", "exact message"),
                                 ("#engineering", "another union message"))]
    comms.channels.catalog.replace(CatalogDocument(
        tags=frozenset({"api", "ui"}),
        preferences={"#engineering": ChannelPreferences(pinned=True, created_at=17)},
        saved_views={"engineering": ActivityView(
            "engineering", ViewPredicate(AnyOfMatch, frozenset({"api", "ui"})), 17,
            frozenset({"#engineering"}))},
    ))
    before = comms.bus.log.path.read_bytes()

    async with workspace.app(size=(110, 35)) as ui:
        sidebar = await channel_roster(ui, "#engineering")
        next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#engineering").row.focus()
        await ui.press("enter")
        chat = ui.textual[0].screen.query_one(CommsChatView)
        await ui.until(lambda: [m.body for m in chat.message_history.messages] == [m.body for m in rows],
                       why="the saved view's history")
        assert chat.prompt.prompt_text_area.disabled
        await ui.until(lambda: "Read-only" in chat.status, why="the read-only status")
        await chat.submit_input(input_events.UserInputSubmitted("must not publish"))
        assert chat.prompt.text == "must not publish"
        assert comms.bus.log.path.read_bytes() == before
        assert next(view for view in comms.views.channel_views() if view.channel.name == "#engineering").channel.pinned
