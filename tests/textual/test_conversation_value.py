"""Typed channel, DM and all-comms values survive actual UI open/send/return."""

import asyncio

from agent_comms.channel_targets import ChannelTarget
from agent_comms.channels import AllChannel
from toad.constants import ALL_COMMS_TARGET
from toad.conversation_kind import ChannelConversation, DmConversation, IrcConversation
from toad.navigation_context import NavigationContext
from toad.navigation_target import DirectTarget, FeedTarget, channel_target
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.channel_activity import ChannelActivity


async def test_channel_dm_and_feed_keep_typed_destinations_through_open_send_and_return(
    workspace,
):
    workspace.thread("peer", "team", title="Conversation peer")
    viewer = workspace.viewer
    workspace.comms.messaging.send("peer", "#team", "CHANNEL_VALUE_HISTORY")
    workspace.comms.messaging.send("peer", viewer, "DM_VALUE_HISTORY")
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        context = NavigationContext(app, owner, workspace.project, viewer)
        for target, expected, body, status_name, destination in (
            (
                channel_target("#team"),
                ChannelConversation(ChannelTarget("#team")),
                "CHANNEL_VALUE_HISTORY",
                "",
                "#team",
            ),
            (
                DirectTarget("peer"),
                DmConversation(workspace.comms.registry.require("peer").incarnation),
                "DM_VALUE_HISTORY",
                "peer",
                "peer",
            ),
            (
                FeedTarget(),
                IrcConversation(ChannelTarget(ALL_COMMS_TARGET)),
                "CHANNEL_VALUE_HISTORY",
                "",
                AllChannel.declared_name,
            ),
        ):
            mode = await target.open(context)
            screen = app.selected_session
            assert screen.navigation_target == target
            await screen.wait_content_ready()
            chat = screen.query_one(CommsChatView)
            await ui.until(
                lambda: body in ui.painted(chat.window),
                why="the conversation's saved message on screen",
            )
            entry = app.session_navigation.get(mode)
            conversation = entry.key.conversation
            assert conversation == expected
            assert screen.conversation is chat.conversation is conversation
            assert chat.message_history.page_source.loader.conversation is conversation
            assert next(
                tab.title for tab in ui.tabs() if tab.identity == mode
            ).startswith(expected.label(
                app.coordination_access.observation.observed()
                .sidebar.observation.require_snapshot().references
            ))
            status = chat.message_history.page_source.status_thread(
                app.coordination_access
            )
            assert status.name == status_name

            outgoing = f"{workspace.roots.attempt.name}: P390_SENT_TO_{destination}"
            await ui.write_draft(outgoing)
            await ui.press("enter")
            await ui.until(
                lambda: outgoing in ui.painted(chat.window),
                why="the sent message returning through Core history",
            )
            (sent,) = (
                fragment.message
                for fragment in chat.message_history.fragments_in_range
                if fragment.message.body == outgoing
            )
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
        workspace.thread(
            "late-peer", "team", running=True, title="Late conversation peer"
        )
        await ui.until(
            lambda: "late-peer" in chat.query_one(ChannelActivity).rows,
            why="the new member in the channel's activity rows",
        )


async def test_renamed_dm_reopens_the_same_tab_and_sends_to_the_current_name(workspace):
    peer = workspace.thread("peer", "team")
    viewer = workspace.viewer
    workspace.comms.messaging.send("peer", viewer, "BEFORE_RENAME")
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        context = NavigationContext(app, owner, workspace.project, viewer)
        mode = await DirectTarget("peer").open(context)
        screen = app.selected_session
        await screen.wait_content_ready()
        chat = screen.query_one(CommsChatView)
        await ui.until(lambda: "BEFORE_RENAME" in ui.painted(chat.window), why="the original DM history")
        entry = app.session_navigation.get(mode)
        window = chat.window
        chat.prompt.text = "draft survives rename"
        await asyncio.to_thread(workspace.comms.registry.rename, "peer", "renamed")
        await ui.until(
            lambda: any(tab.identity == mode and tab.title == "@renamed" for tab in ui.tabs()),
            why="the retained DM tab following its incarnation's current name",
        )
        await ui.select_tab(owner)
        assert await DirectTarget("renamed").open(context) == mode
        assert app.session_navigation.get(mode) is entry
        assert app.selected_session is screen
        assert screen.query_one(CommsChatView) is chat
        assert chat.window is window
        assert entry.key.conversation.peer == peer.incarnation
        assert chat.prompt.text == "draft survives rename"
        assert "BEFORE_RENAME" in ui.painted(window)
        await ui.write_draft("AFTER_RENAME")
        await ui.press("enter")
        await ui.until(lambda: "AFTER_RENAME" in ui.painted(window), why="a fresh send to the renamed peer")
        sent = [fragment.message for fragment in chat.message_history.fragments_in_range if fragment.message.body == "AFTER_RENAME"]
        assert len(sent) == 1
        assert sent[0].target == "renamed"
