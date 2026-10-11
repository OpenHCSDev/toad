"""Textual-facing: the channels sidebar's expansion, scroll position and range anchor survive switching between views, painted identically from its first ready frame."""

from support.stylesheets import INSTALLED
from support.textual_steps import channel_roster, coordination_update
from toad.app import ToadApp
from toad.screens.main import MainScreen
from toad.session_tracker import SidebarSelection
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar


class FrameApp(ToadApp):
    """Records the sidebar panel text of every frame drawn while `panel_frames` is a list."""

    CSS_PATH = INSTALLED

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.panel_frames = None

    def panel_text(self, screen):
        sidebar = screen.query_one_optional(CommsSidebar)
        if sidebar is None:
            return ()
        region = sidebar.navigation.scroll_container.content_region
        return tuple(strip.text[region.x:region.right]
                     for strip in screen._compositor.render_strips()[region.y:region.bottom])

    def _display(self, screen, renderable):
        if (self.panel_frames is not None and renderable is not None and not self._batch_count
                and screen is self.screen and screen.query_one_optional(CommsSidebar) is not None):
            sidebar = screen.query_one(CommsSidebar)
            self.panel_frames.append((self.selected_mode, sidebar.navigation.ready.is_set(), self.panel_text(screen)))
        return super()._display(screen, renderable)


def group(view, name):
    return next(item for item in view.query(ChannelGroup) if item.row.target_name == name)


async def settled(ui, view):
    await ui.until(view.navigation.ready.is_set, seconds=5, why="the sidebar to be ready")
    await ui.step()


async def test_sidebar_expansion_scroll_and_anchor_survive_view_changes(workspace):
    channels = [f"channel-{index:02}" for index in range(30)]
    workspace.thread("worker", "experiment", *channels, running=True)
    for name in channels:
        workspace.comms.channels.create_tag(name)
    async with workspace.app(size=(100, 30), application=FrameApp) as ui:
        app, pilot = ui.textual
        app.workspace_chrome.channels.reveal()
        await app.workspace_chrome.channels.wait_content_ready()
        await ui.step()
        owner = ui.selected_tab
        worker = await app.session_navigation.new(
            lambda: MainScreen(workspace.project, agent_session_id="worker"))
        await app.selected_session.on_coordination_update(
            coordination_update(str(workspace.roots.wire), "worker"))
        await ui.select_tab(owner)
        sidebar = await channel_roster(ui, "#any", "#channel-28")

        group(sidebar, "#any").toggle_members()
        selected = group(sidebar, "#channel-28")
        selected.toggle_members()
        await ui.step()
        selected.row.scroll_visible(animate=False)
        selected.row.focus(scroll_visible=False)
        await ui.step()
        await pilot.wait_for_scheduled_animations()
        expected_scroll = sidebar.navigation.scroll_container.scroll_y
        assert expected_scroll > 0, [
            (type(widget).__name__, widget.size, widget.virtual_size, widget.scroll_y, widget.max_scroll_y)
            for widget in (sidebar, *sidebar.ancestors) if hasattr(widget, "virtual_size")]
        expected_frame = app.panel_text(app.screen)
        app.panel_frames = []
        selected.row.action_open_selected()
        await ui.step()
        channel_mode = ui.selected_tab
        assert channel_mode != owner
        current = app.screen.query_one(CommsSidebar)
        await settled(ui, current)
        assert app.panel_frames and any(mode == channel_mode and ready for mode, ready, _ in app.panel_frames)
        assert all(frame == expected_frame for _, ready, frame in app.panel_frames if ready), app.panel_frames
        app.panel_frames = None
        assert group(current, "#channel-28").expanded
        assert not group(current, "#any").expanded
        actual_scroll = current.navigation.scroll_container.scroll_y
        assert actual_scroll == expected_scroll, (
            actual_scroll, expected_scroll, app.sidebar_state,
            (current.navigation.scroll_container.scroll_y, current.navigation.scroll_container.max_scroll_y))
        assert app.sidebar_state.selected == SidebarSelection("#channel-28", "#channel-28")
        group(current, "#channel-28").toggle_members()
        await ui.step()
        await pilot.wait_for_scheduled_animations()
        expected_scroll = current.navigation.scroll_container.scroll_y
        await ui.select_tab(owner)
        await settled(ui, sidebar)
        assert not group(sidebar, "#channel-28").expanded
        assert not group(sidebar, "#any").expanded
        actual_scroll = sidebar.navigation.scroll_container.scroll_y
        assert actual_scroll == expected_scroll, (actual_scroll, expected_scroll)
        assert app.sidebar_state.selected == SidebarSelection("#channel-28", "#channel-28")
        nested = group(sidebar, "#channel-28")
        nested.toggle_members()
        await ui.step()
        member = nested.members["worker"]
        member.scroll_visible(animate=False)
        member.focus(scroll_visible=False)
        await ui.step()
        await pilot.wait_for_scheduled_animations()
        expected_scroll = sidebar.navigation.scroll_container.scroll_y
        member.action_open_selected()
        # Opening a row makes it the range anchor; it does not select it (TargetTree.remember_row).
        assert not any(row.has_class("-selected") for row in sidebar._ordered_rows())
        expected_frame = app.panel_text(app.screen)
        app.panel_frames = []
        await ui.until(
            lambda: ui.selected_tab == worker.mode_name
            and any(mode == worker.mode_name and ready for mode, ready, _ in app.panel_frames),
            seconds=5, why="the worker view's ready sidebar to be drawn")
        current = app.screen.query_one(CommsSidebar)
        await settled(ui, current)
        assert app.panel_frames and any(mode == worker.mode_name and ready for mode, ready, _ in app.panel_frames)
        assert all(frame == expected_frame for _, ready, frame in app.panel_frames if ready), app.panel_frames
        app.panel_frames = None
        assert ui.selected_tab == worker.mode_name
        assert group(current, "#channel-28").expanded
        assert not group(current, "#any").expanded
        assert app.sidebar_state.selected == SidebarSelection("#channel-28", "worker")
        member = group(current, "#channel-28").members["worker"]
        assert member.current
        assert not any(row.has_class("-selected") for row in current._ordered_rows())
        await pilot.hover(member)
        assert "hover" in member.pseudo_classes and not member.has_focus, (
            member.region, member.pseudo_classes, member.has_focus,
            app.get_widget_at(member.region.x, member.region.y), current.navigation.scroll_container.region)
        await pilot.hover(ui.conversation.prompt)
        assert "hover" not in member.pseudo_classes and member.current
        assert current.navigation.scroll_container.scroll_y == expected_scroll
