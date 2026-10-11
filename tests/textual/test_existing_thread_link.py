"""Textual-facing: clicking a thread link in a conversation or a chat selects the thread's already-open tab, without a provisional tab or route discovery."""

from unittest.mock import patch

from textual.containers import VerticalGroup

from toad.block_navigation import ConversationBlock
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.goal_bar import GoalBar
from toad.widgets.irc_message import ThreadLink
from toad.widgets.session_tabs import SessionsTabs, Underline


class LinkBlock(ConversationBlock, VerticalGroup):
    """A conversation block holding one thread link."""

    def __init__(self, target):
        super().__init__()
        self.link = ThreadLink(target)

    def compose(self):
        yield self.link


async def test_link_to_an_open_thread_selects_its_tab_and_creates_nothing(workspace):
    workspace.thread("owner", running=True)
    workspace.thread("peer", running=True)
    wire_root = str(workspace.roots.wire)
    async with workspace.app(size=(100, 36)) as ui:
        app, pilot = ui.textual
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
        block = LinkBlock("peer")
        link = block.link
        await source.conversation.contents.mount(block)
        await ui.step()
        order = ui.tabs()
        with patch.object(app.navigation_reader, "read", wraps=app.navigation_reader.read) as reads:
            assert await pilot.click(link)
            await ui.until(lambda: ui.selected_tab == existing, seconds=3, why="the open thread's tab")
            assert app.selected_session is destination and ui.selected_tab != foreign
            assert reads.call_count == 0, "Existing mounted identity needed route discovery"
            assert ui.tabs() == order
            assert ui.draft() == "Keep this draft"
            assert not app.thread_navigation.pending
            # Repeated and self links reuse the very same mounted tab too.
            for _ in range(2):
                assert await app.thread_navigation.open(
                    owner_mode=existing, project_path=workspace.project, target="peer") == existing
            assert reads.call_count == 0
            assert ui.tabs() == order


async def test_link_clicked_in_a_chat_view_reuses_the_open_thread_tab(workspace):
    workspace.thread("owner")
    workspace.thread("peer")
    wire_root = str(workspace.roots.wire)
    async with workspace.app(size=(100, 36)) as ui:
        app, pilot = ui.textual
        owner = ui.selected_tab
        existing = await ui.new_session()
        destination = app.selected_session
        destination.initial_coordination_root = wire_root
        destination._comms_thread = "peer"
        await ui.write_draft("Keep this draft")
        # Chat views inherit the conversation's mouse handlers but omit goal
        # controls. A real link click must still reuse the tab.
        await ui.new_session()
        await ui.open_channel("peer", actor="owner", owner=owner)
        chat = app.screen.query_one(CommsChatView)
        assert chat.query_one_optional(GoalBar) is None
        await ui.resize(65, 36)
        tabs = app.screen.query_one(SessionsTabs)
        assert tabs.show_horizontal_scrollbar
        underline = tabs.query_one(Underline)
        clip = app.screen._compositor.find_widget(underline).clip
        assert underline.region.intersection(clip).height == 1
        block = LinkBlock("peer")
        chat_link = block.link
        await chat.contents.mount(block)
        chat_link.scroll_visible(animate=False)
        await ui.step()
        order = ui.tabs()
        assert await pilot.click(chat_link)
        await ui.until(lambda: ui.selected_tab == existing, seconds=3, why="the open thread's tab")
        assert app.selected_session is destination
        assert ui.tabs() == order
        assert ui.draft() == "Keep this draft"
