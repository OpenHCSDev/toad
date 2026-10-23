"""Textual-facing: the conversation tabs; typed channel, DM and all-comms values survive actual UI open/send/return."""

import asyncio

from agent_comms.channel_targets import ChannelTarget
from agent_comms.channels import AllChannel
from toad.constants import ALL_COMMS_TARGET
from toad.conversation_kind import ChannelConversation, DmConversation, IrcConversation
from toad.navigation_target import NavigationContext
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
                AllChannel.address(),
            ),
        ):
            mode = await target.open(context)
            screen = app.selected_session
            assert screen.navigation_target_name == target.name
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
        late_peer = workspace.thread(
            "late-peer", "team", running=True, title="Late conversation peer"
        )
        activity = chat.query_one(ChannelActivity)
        await ui.until(
            lambda: late_peer.incarnation in activity.rows,
            why="the new member in the channel's activity rows",
        )
        member = activity.rows[late_peer.incarnation]
        await asyncio.to_thread(workspace.comms.registry.rename, "late-peer", "renamed-late-peer")
        await ui.until(
            lambda: member.label == "renamed-late-peer",
            why="the retained activity row following its peer's current name",
        )
        assert activity.rows[late_peer.incarnation] is member


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
            lambda: any(tab.identity == mode and tab.title.startswith("@renamed") for tab in ui.tabs()),
            why="the retained DM tab following its incarnation's current name",
        )
        assert next(tab.title for tab in app.open_tabs if tab.mode_name == mode) == "@renamed"
        history = chat.message_history
        await ui.until(
            lambda: history.source_ready
            and history.revision.selection.peer.name == "renamed"
            and history.revision.selection.peer == peer.incarnation
            and "BEFORE_RENAME" in ui.painted(window),
            why="the renamed conversation's captured source and painted message",
        )
        fragments = history.fragments_in_range
        width, theme = history.line_width, app.colours.line_theme
        lines = tuple(fragment.lines_for(width, theme) for fragment in fragments)
        assert lines and all(value is not None for value in lines)
        await ui.select_tab(owner)
        assert await ui.open_direct("renamed", actor=viewer, owner=owner) == mode
        assert app.session_navigation.get(mode) is entry
        assert app.selected_session is screen
        assert screen.query_one(CommsChatView) is chat
        assert chat.window is window
        assert all(before is after for before, after in zip(
            fragments, history.fragments_in_range, strict=True,
        ))
        assert history.line_width == width
        assert all(before is fragment.lines_for(width, theme) for before, fragment in zip(
            lines, history.fragments_in_range, strict=True,
        ))
        assert entry.key.conversation.peer == peer.incarnation
        assert chat.prompt.text == "draft survives rename"
        assert "BEFORE_RENAME" in ui.painted(window)
        await ui.write_draft("AFTER_RENAME")
        await ui.press("enter")
        await ui.until(lambda: "AFTER_RENAME" in ui.painted(window), why="a fresh send to the renamed peer")
        sent = [fragment.message for fragment in chat.message_history.fragments_in_range if fragment.message.body == "AFTER_RENAME"]
        assert len(sent) == 1
        assert sent[0].target == "renamed"


async def test_recreated_dm_peer_retires_the_old_view_and_opens_a_new_incarnation(workspace):
    peer = workspace.thread("peer", "team")
    viewer = workspace.viewer
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        context = NavigationContext(app, owner, workspace.project, viewer)
        old_mode = await DirectTarget("peer").open(context)
        old_screen = app.selected_session
        await old_screen.wait_content_ready()
        old_chat = old_screen.query_one(CommsChatView)
        old_window = old_chat.window
        old_chat.prompt.text = "belongs only to the original peer"

        def replace_peer():
            registry = workspace.comms.registry
            registry.unregister(peer.name)
            registry.remove_originals((registry.require(peer.name),))
            return registry.declare(registry.new_thread(
                peer.name, peer.tags, peer.worktree, created_at=peer.created_at + 1,
            ))

        successor = await asyncio.to_thread(replace_peer)
        await ui.until(
            lambda: app.session_navigation.get(old_mode) is None,
            why="Core retiring the deleted peer's visible DM view",
        )
        await ui.select_tab(owner)
        new_mode = await DirectTarget("peer").open(context)
        screen = app.selected_session
        await screen.wait_content_ready()
        chat = screen.query_one(CommsChatView)
        entry = app.session_navigation.get(new_mode)
        assert new_mode != old_mode
        assert screen is not old_screen
        assert chat is not old_chat
        assert chat.window is not old_window
        assert entry.key.conversation.peer == successor.incarnation
        assert entry.key.conversation.peer != peer.incarnation
        assert chat.prompt.text == ""
        await ui.write_draft("FOR_THE_SUCCESSOR")
        await ui.press("enter")
        await ui.until(
            lambda: "FOR_THE_SUCCESSOR" in ui.painted(chat.window),
            why="a fresh message in the successor's distinct DM view",
        )
        sent = [fragment.message for fragment in chat.message_history.fragments_in_range
                if fragment.message.body == "FOR_THE_SUCCESSOR"]
        assert len(sent) == 1
        assert sent[0].target == successor.name
