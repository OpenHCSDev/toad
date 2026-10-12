"""Textual-facing: clicking a thread's name in a chat selects the thread's already-open tab, without a provisional tab or route discovery."""

from unittest.mock import patch

from toad.widgets.comms_chat import CommsChatView
from toad.widgets.goal_bar import GoalBar
from toad.widgets.session_tabs import SessionsTabs, Underline


async def test_name_of_an_open_thread_selects_its_tab_and_creates_nothing(workspace):
    workspace.thread("owner", "team", running=True)
    workspace.thread("peer", "team", running=True)
    workspace.comms.messaging.send("peer", "#team", "a message from the open thread")
    wire_root = str(workspace.roots.wire)
    async with workspace.app(size=(100, 36)) as ui:
        app, _pilot = ui.textual
        owner = ui.selected_tab
        source = app.selected_session
        source.initial_coordination_root = wire_root
        source._comms_thread = "owner"
        foreign = await ui.new_session()
        app.selected_session.initial_coordination_root = str(workspace.project / "foreign-wire")
        app.selected_session._comms_thread = "peer"
        existing = await ui.new_session()
        destination = app.selected_session
        destination.initial_coordination_root = wire_root
        destination._comms_thread = "peer"
        await ui.write_draft("Keep this draft")
        await ui.select_tab(owner)
        await ui.open_channel("#team", actor="owner", owner=owner)
        await ui.until_shows("peer → #team")
        await ui.until(lambda: ui.link_at("peer → #team") == ("open_target", ("peer",)), why="the sender drawn as a link")
        # The channel tab's unread count clears as its message is read; the tabs themselves must not change.
        def order():
            return [tab.identity for tab in ui.tabs()]

        opened = order()
        with patch.object(app.navigation_reader, "read", wraps=app.navigation_reader.read) as reads:
            await ui.click("peer → #team")
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
    workspace.comms.messaging.send("peer", viewer, "a direct message")
    wire_root = str(workspace.roots.wire)
    async with workspace.app(size=(100, 36)) as ui:
        app, _pilot = ui.textual
        owner = ui.selected_tab
        existing = await ui.new_session()
        destination = app.selected_session
        destination.initial_coordination_root = wire_root
        destination._comms_thread = "peer"
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
        await ui.until_shows(f"peer → {viewer}")
        await ui.until(lambda: ui.link_at(f"peer → {viewer}") == ("open_target", ("peer",)), why="the sender drawn as a link")
        # The chat tab's title drops its unread count once the message is marked read.
        order = [tab.identity for tab in ui.tabs()]
        await ui.click(f"peer → {viewer}")
        await ui.until(lambda: ui.selected_tab == existing, seconds=3, why="the open thread's tab")
        assert app.selected_session is destination
        assert [tab.identity for tab in ui.tabs()] == order
        assert ui.draft() == "Keep this draft"
