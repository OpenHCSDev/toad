"""Textual-facing: a saved view opens from the sidebar as normal history with a disabled composer (widget state)."""

from agent_comms.catalog_document import CatalogDocument, ChannelPreferences
from agent_comms.messaging.channels import (
    ActivityView,
    AnyOfMatch,
    ViewPredicate,
)

from support.textual_steps import channel_roster


async def test_saved_view_shows_union_history_keeps_its_pin_and_refuses_to_send(workspace):
    from toad.core import input_events
    from toad.widgets.comms_chat import CommsChatView
    from toad.widgets.comms_sidebar import ChannelGroup

    workspace.thread(workspace.project.name, running=True)
    workspace.thread("api-agent", "api", running=True)
    workspace.thread("ui-agent", "ui", running=True)
    comms = workspace.comms
    # The catalog declares the channels before anything is published to them.
    comms.channels.catalog.replace(CatalogDocument(
        tags=frozenset({"api", "ui"}),
        preferences={"#engineering": ChannelPreferences(pinned=True, created_at=17),
                     "#api": ChannelPreferences(created_at=17), "#ui": ChannelPreferences(created_at=17)},
        saved_views={"engineering": ActivityView(
            "engineering", ViewPredicate(AnyOfMatch, frozenset({"api", "ui"})), 17,
            frozenset({"#engineering"}))},
    ))
    rows = [comms.messaging.send("api-agent", target, body).message
            # A saved view is a projection: it routes nothing, and shows what its tags' channels hold.
            for target, body in (("#ui", "union message"), ("#api", "exact message"),
                                 ("#ui", "another union message"))]
    before = comms.views.latest_sequence()

    async with workspace.app(size=(110, 35)) as ui:
        sidebar = await channel_roster(ui, "#engineering")
        next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#engineering").row.focus()
        await ui.press("enter")
        screen = ui.textual[0].screen
        await ui.until(lambda: screen.query(CommsChatView), why="the saved view's chat")
        chat = screen.query_one(CommsChatView)
        await ui.until(lambda: [fragment.message.body for fragment in chat.message_history.fragments_in_range]
                       == [m.body for m in rows],
                       why="the saved view's history")
        await ui.until(lambda: "Read-only" in chat.status, why="the read-only status")
        assert chat.prompt.prompt_text_area.disabled
        await (await chat.submissions.submit(input_events.UserInputSubmitted("must not publish"))).wait()
        assert chat.prompt.text == "must not publish"
        assert comms.views.latest_sequence() == before
        assert next(view for view in comms.views.channel_views() if view.channel.name == "#engineering").channel.pinned
