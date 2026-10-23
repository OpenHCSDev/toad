"""Textual-facing: clicking a thread's name in a chat selects the thread's already-open tab, without a provisional tab or route discovery."""

from unittest.mock import patch

from toad.line_blocks import OpenTarget
from toad.message_rows import MessageRow
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.goal_bar import GoalBar
from toad.widgets.session_tabs import SessionsTabs, Underline


async def test_name_of_an_open_thread_selects_its_tab_and_creates_nothing(workspace):
    workspace.thread("owner", "team", running=True)
    workspace.thread("peer", "team", running=True)
    message = workspace.comms.messaging.send("peer", "#team", "a message from the open thread").message
    header = MessageRow(message, "owner").header
    sender = OpenTarget("peer")
    foreign_root = workspace.project / "foreign-wire"
    workspace.thread("peer", "team", running=True, root=foreign_root)
    async with workspace.app(size=(100, 36)) as ui:
        app, _pilot = ui.textual
        owner = ui.selected_tab
        source = app.selected_session
        await workspace.bind(source, "owner")
        foreign = await ui.new_session()
        await workspace.bind(app.selected_session, "peer", root=foreign_root)
        existing = await ui.new_session()
        destination = app.selected_session
        await workspace.bind(destination, "peer")
        await ui.write_draft("Keep this draft")
        await ui.select_tab(owner)
        await ui.open_channel("#team", actor="owner", owner=owner)
        await ui.until_shows(header.label)
        await ui.until(lambda: app.screen.get_style_at(*ui.link_cell(header, sender)).meta.get("@click") == sender.click,
                       why="the sender drawn as a link")
        # The channel tab's unread count clears as its message is read; the tabs themselves must not change.
        def order():
            return [tab.identity for tab in ui.tabs()]

        opened = order()
        with patch.object(app.navigation_reader, "read", wraps=app.navigation_reader.read) as reads:
            assert await ui.pilot.click(offset=ui.link_cell(header, sender))
            await ui.step()
            await ui.until(lambda: ui.selected_tab == existing, seconds=3, why="the open thread's tab")
            assert app.selected_session is destination and ui.selected_tab != foreign
            assert reads.call_count == 0, "Existing mounted identity needed route discovery"
            assert order() == opened
            assert ui.draft() == "Keep this draft"
            assert not app.thread_navigation.pending
            # Repeated and self links reuse the very same mounted tab too.
            for _ in range(2):
                assert await app.thread_navigation.open(
                    owner_mode=existing, project_path=workspace.project, target="peer") == existing
            assert reads.call_count == 0
            assert order() == opened


async def test_name_clicked_in_a_narrow_direct_chat_reuses_the_open_thread_tab(workspace):
    workspace.thread("owner")
    workspace.thread("peer")
    viewer = workspace.viewer
    message = workspace.comms.messaging.send("peer", viewer, "a direct message").message
    header = MessageRow(message, viewer).header
    sender = OpenTarget("peer")
    async with workspace.app(size=(100, 36)) as ui:
        app, _pilot = ui.textual
        owner = ui.selected_tab
        existing = await ui.new_session()
        destination = app.selected_session
        await workspace.bind(destination, "peer")
        await ui.write_draft("Keep this draft")
        # Chat views inherit the conversation's mouse handlers but omit goal
        # controls. A real click on a name must still reuse the tab.
        await ui.new_session()
        await ui.open_direct("peer", actor=viewer, owner=owner)
        chat = app.screen.query_one(CommsChatView)
        assert chat.query_one_optional(GoalBar) is None
        await ui.resize(65, 36)
        tabs = app.screen.query_one(SessionsTabs)
        assert tabs.show_horizontal_scrollbar
        underline = tabs.query_one(Underline)
        clip = app.screen._compositor.find_widget(underline).clip
        assert underline.region.intersection(clip).height == 1
        await ui.until_shows(header.label)
        await ui.until(lambda: app.screen.get_style_at(*ui.link_cell(header, sender)).meta.get("@click") == sender.click,
                       why="the sender drawn as a link")
        # The chat tab's title drops its unread count once the message is marked read.
        order = [tab.identity for tab in ui.tabs()]
        assert await ui.pilot.click(offset=ui.link_cell(header, sender))
        await ui.step()
        await ui.until(lambda: ui.selected_tab == existing, seconds=3, why="the open thread's tab")
        assert app.selected_session is destination
        assert [tab.identity for tab in ui.tabs()] == order
        assert ui.draft() == "Keep this draft"
