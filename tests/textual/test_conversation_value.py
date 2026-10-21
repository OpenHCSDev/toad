"""Typed channel, DM and all-comms values survive actual UI open/send/return."""

from agent_comms.channel_targets import ChannelTarget, ThreadTarget
from agent_comms.channels import AllChannel
from toad.constants import ALL_COMMS_TARGET
from toad.conversation_kind import ChannelConversation, DmConversation, IrcConversation
from toad.navigation_context import NavigationContext
from toad.navigation_target import DirectTarget, FeedTarget, channel_target
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.channel_activity import ChannelActivity


async def test_channel_dm_and_feed_keep_typed_destinations_through_open_send_and_return(workspace):
    workspace.thread("peer", "team", title="Conversation peer")
    viewer = workspace.viewer
    workspace.comms.messaging.send("peer", "#team", "CHANNEL_VALUE_HISTORY")
    workspace.comms.messaging.send("peer", viewer, "DM_VALUE_HISTORY")
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        context = NavigationContext(app, owner, workspace.project, viewer)
        for target, expected, body, status_name, destination in (
            (channel_target("#team"), ChannelConversation(ChannelTarget("#team")),
             "CHANNEL_VALUE_HISTORY", "", "#team"),
            (DirectTarget("peer"), DmConversation(ThreadTarget("peer")),
             "DM_VALUE_HISTORY", "peer", "peer"),
            (FeedTarget(), IrcConversation(ChannelTarget(ALL_COMMS_TARGET)),
             "CHANNEL_VALUE_HISTORY", "", AllChannel.declared_name),
        ):
            mode = await target.open(context)
            screen = app.selected_session
            assert screen.navigation_target == target
            await screen.wait_content_ready()
            chat = screen.query_one(CommsChatView)
            await ui.until(lambda: body in ui.painted(chat.window),
                           why="the conversation's saved message on screen")
            entry = app.session_navigation.get(mode)
            conversation = entry.key.conversation
            assert conversation == expected
            assert screen.conversation is chat.conversation is conversation
            assert chat.message_history.page_source.loader.conversation is conversation
            assert next(tab.title for tab in ui.tabs() if tab.identity == mode).startswith(expected.label())
            status = chat.message_history.page_source.status_thread(app.coordination_access)
            assert status.name == status_name

            outgoing = f"{workspace.roots.attempt.name}: P390_SENT_TO_{destination}"
            await ui.write_draft(outgoing)
            await ui.press("enter")
            await ui.until(lambda: outgoing in ui.painted(chat.window),
                           why="the sent message returning through Core history")
            sent, = (fragment.message for fragment in chat.message_history.fragments_in_range
                     if fragment.message.body == outgoing)
            assert (sent.sender, sent.target) == (viewer, destination)

            chat.prompt.text = "retained draft"
            await ui.select_tab(owner)
            assert await target.open(context) == mode
            assert app.selected_session is screen
            assert chat.prompt.text == "retained draft"
            assert chat.message_history.page_source.loader.conversation is conversation
            await ui.select_tab(owner)

        await channel_target("#team").open(context)
        chat = app.selected_session.query_one(CommsChatView)
        workspace.thread("late-peer", "team", running=True, title="Late conversation peer")
        await ui.until(lambda: "late-peer" in chat.query_one(ChannelActivity).rows,
                       why="the new member in the channel's activity rows")
