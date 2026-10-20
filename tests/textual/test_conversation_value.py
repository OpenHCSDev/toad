"""Channel and DM navigation retain one resolved value through the actual app."""

from agent_comms.launch_root import LaunchRoot
from toad.conversation_kind import ChannelConversation, DmConversation
from toad.navigation_target import DirectTarget, NavigationContext, channel_target
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.channel_activity import ChannelActivity


async def test_channel_and_dm_keep_the_conversation_through_open_and_return(workspace):
    LaunchRoot.from_path(workspace.roots.wire).install()
    workspace.thread("peer", "team")
    viewer = workspace.viewer
    workspace.comms.messaging.send("peer", "#team", "CHANNEL_VALUE_HISTORY")
    workspace.comms.messaging.send("peer", viewer, "DM_VALUE_HISTORY")
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        context = NavigationContext(app, owner, workspace.project, viewer)
        for target, expected, body in (
            (channel_target("#team"), ChannelConversation("#team"), "CHANNEL_VALUE_HISTORY"),
            (DirectTarget("peer"), DmConversation("peer"), "DM_VALUE_HISTORY"),
        ):
            mode = await target.open(context)
            screen = app.selected_session
            await screen.wait_content_ready()
            chat = screen.query_one(CommsChatView)
            await ui.until(lambda: body in ui.painted(chat.window),
                           why="the conversation's saved message on screen")
            entry = app.session_navigation.get(mode)
            conversation = entry.key.conversation
            assert conversation == expected
            assert screen.conversation is chat.conversation is conversation
            assert chat.message_history.page_source.loader.conversation is conversation
            if isinstance(conversation, ChannelConversation):
                # Membership invalidation must consume the chat's conversation too.
                workspace.thread("late-peer", "team", running=True)
                await ui.until(lambda: "late-peer" in chat.query_one(ChannelActivity).rows,
                               why="the new member in the channel's activity rows")
            chat.prompt.text = "retained draft"
            await ui.select_tab(owner)
            assert await target.open(context) == mode
            assert app.selected_session is screen
            assert chat.prompt.text == "retained draft"
            assert chat.message_history.page_source.loader.conversation is conversation
            await ui.select_tab(owner)
