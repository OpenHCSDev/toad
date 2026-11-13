"""Textual-facing: a hidden view's thread sidebar keeps its styles and layout while the shared channels sidebar changes, and the first frame of an activated view already shows the sidebar as the user left it."""

from toad.widgets.side_bar import ThreadSidebar
from toad.widgets.channels_sidebar import ChannelsSidebar
from agent_comms.projects.checkouts import Checkout
from agent_comms.messaging.channel_targets import CommandTarget

from toad.app import ToadApp
from toad.widgets.side_bar import SideBar


async def test_view_menu_discovers_settings_and_keeps_each_objects_state(workspace):
    from toad.configured_view import ObjectProperties
    from toad.forms.object_configuration import ObjectValueView
    from toad.preferences import SETTINGS
    from toad.widgets.side_bar import PanelMenu
    from toad.widgets.thread_comms import ThreadCommsSidebar

    workspace.comms.channels.create_tag('settings')
    preview = workspace.project / 'example.txt'
    preview.write_text('A viewed file\n')
    async with workspace.app(size=(140, 45)) as ui:
        app, pilot = ui.textual
        original = ui.selected_tab
        channel = await ui.open_channel('#settings', actor=workspace.viewer)
        view = app.workspace_sessions.require(channel)
        bar = await ui.revealed(view.thread_sidebar)
        menu = bar.query_one(PanelMenu)
        assert not bar.query(ThreadCommsSidebar)
        assert menu.entries and all(isinstance(entry.widget, ObjectProperties) for entry in menu.entries)
        assert len(menu.pages) == 1
        state = view.configuration_state
        assert state.identity == app.session_navigation.get(channel).identity
        await ui.until(lambda: bool(menu.query(ObjectValueView)), why='selected settings fields')
        assert 'ui.column_width' in {part.field.path.value for part in menu.query(ObjectValueView)}
        assert menu.region.width and menu.query_one(ObjectValueView).region.height
        ui_entry = menu.picker.value
        other = next(entry for entry in menu.entries if entry is not ui_entry)
        menu.picker.value = other
        await ui.until(lambda: menu.navigation.panel_identity == other.widget.panel_identity, why='dropdown selection')
        menu.picker.value = ui_entry
        await ui.until(lambda: menu.navigation.panel_identity == ui_entry.widget.panel_identity, why='returning to settings')
        app.saved_settings.set(SETTINGS.ui.column_width, 83)
        assert state.fields.ui.column_width == 83
        state.field('ui.column_width').edit(91)
        app.saved_settings.set(SETTINGS.ui.column_width, 85)
        assert state.fields.ui.column_width == 91
        state.reset_parameter('ui.column_width')
        assert state.fields.ui.column_width == 85
        file_mode = await ui.open_preview(preview)
        file_view = app.workspace_sessions.require(file_mode)
        file_bar = await ui.revealed(file_view.thread_sidebar)
        file_menu = file_bar.query_one(PanelMenu)
        assert file_view.configuration_state.identity == app.session_navigation.get(file_mode).identity
        assert file_view.configuration_state is not state
        assert not file_bar.query(ThreadCommsSidebar)
        assert len(file_menu.entries) < len(menu.entries)
        await ui.select_tab(channel)
        assert view.thread_sidebar is bar and bar.query_one(PanelMenu) is menu
        assert menu.picker.value is ui_entry
        view.open_configuration()
        await ui.step()
        dialog = app.screen
        assert all(entry.widget.field.state is state for entry in dialog.form.entries)
        await ui.until(lambda: bool(dialog.query(ObjectValueView)), why='the shared context editor')
        dialog.dismiss_control()
        await ui.step()
        await ui.select_tab(original)
        native = app.workspace_sessions.require(original)
        workspace.thread('panel-owner')
        await workspace.bind(native, 'panel-owner')
        native_bar = await ui.revealed(native.thread_sidebar)
        native_menu = native_bar.query_one(PanelMenu)
        relationships = next(entry for entry in native_menu.entries
                             if isinstance(entry.widget, ThreadCommsSidebar))
        native_menu.picker.value = relationships
        await ui.until(lambda: relationships.widget.is_mounted, why='the native relationship panel')
        assert relationships.widget.panel_visible
        relationships.widget._visible()
        settings_entry = next(entry for entry in native_menu.entries
                              if isinstance(entry.widget, ObjectProperties))
        native_menu.picker.value = settings_entry
        await ui.until(lambda: not relationships.widget.panel_visible, why='the hidden native panel')


class FrameApp(ToadApp):
    """Records the channels sidebar's collapsed state, width and panel visibility of every frame drawn while `frames` is a list."""


    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = None

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if (self.frames is not None and renderable is not None and not self._batch_count
                and screen is self.screen):
            sidebar = screen.query_one_optional(ChannelsSidebar)
            if sidebar is not None:
                self.frames.append((self.selected_mode, sidebar.collapsed, sidebar.size.width,
                                    sidebar.content_stack.display))
        return result


async def test_hidden_sidebars_keep_geometry_and_activated_views_first_frame_matches_intent(workspace):
    viewer = workspace.viewer
    workspace.comms.channels.create_tag("projection")
    workspace.comms.messaging.send_user_message(
        CommandTarget.named("#projection"), "Channel history", worktree=Checkout(workspace.project)
    )
    async with workspace.app(size=(120, 40), application=FrameApp) as ui:
        app, _ = ui.textual
        first = ui.selected_tab
        second = await ui.new_session()
        channel = await ui.open_channel("#projection", actor=viewer)
        modes = [first, second, channel]
        for mode in modes:
            await ui.select_tab(mode)
        await ui.select_tab(first)
        shared = app.screen.query_one(ChannelsSidebar)
        thread_bars = {mode: app.workspace_sessions.require(mode).query_one(ThreadSidebar)
                       for mode in modes}
        shared.reveal()
        await ui.step()
        hidden_styles = {mode: thread_bars[mode].styles.get_rules() for mode in (second, channel)}
        hidden_layouts = {mode: thread_bars[mode]._layout_updates for mode in (second, channel)}
        right_states = {mode: thread_bars[mode].collapsed for mode in modes}
        shared.toggle()
        await ui.step()
        assert shared.collapsed
        for mode in (second, channel):
            assert thread_bars[mode].styles.get_rules() == hidden_styles[mode]
            assert thread_bars[mode]._layout_updates == hidden_layouts[mode]
        shared.toggle()
        await ui.step()
        for mode in (second, channel):
            assert thread_bars[mode].styles.get_rules() == hidden_styles[mode]
            assert thread_bars[mode]._layout_updates == hidden_layouts[mode]

        # A one-way hidden collapse must be applied before its first frame,
        # for both native thread and channel views.
        shared.toggle()
        await ui.step()
        app.frames = []
        for mode in (second, channel):
            await ui.select_tab(mode)
            frames = [frame for frame in app.frames if frame[0] == mode]
            assert frames and all(collapsed and width == 3 and not panels
                                  for _, collapsed, width, panels in frames), frames
        app.frames = None
        shared.reveal()
        await ui.step()
        app.frames = []
        await ui.select_tab(first)
        frames = [frame for frame in app.frames if frame[0] == first]
        assert frames and all(not collapsed and width > 3 and panels
                              for _, collapsed, width, panels in frames), frames
        for mode in modes:
            assert thread_bars[mode].collapsed == right_states[mode]
