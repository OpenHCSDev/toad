"""Textual-facing: a hidden view's thread sidebar keeps its styles and layout while the shared channels sidebar changes, and the first frame of an activated view already shows the sidebar as the user left it."""

from support.stylesheets import INSTALLED
from toad.app import ToadApp
from toad.widgets.side_bar import SideBar


class FrameApp(ToadApp):
    """Records the channels sidebar's collapsed state, width and panel visibility of every frame drawn while `frames` is a list."""

    CSS_PATH = INSTALLED

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = None

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if (self.frames is not None and renderable is not None and not self._batch_count
                and screen is self.screen):
            sidebar = screen.query_one_optional("#channels-sidebar", SideBar)
            if sidebar is not None:
                self.frames.append((self.selected_mode, sidebar.collapsed, sidebar.size.width,
                                    sidebar.panels_viewport.display))
        return result


async def test_hidden_sidebars_keep_geometry_and_activated_views_first_frame_matches_intent(workspace):
    viewer = workspace.viewer
    workspace.thread(viewer, "fixture")
    workspace.comms.channels.create_tag("projection")
    workspace.comms.messaging.send(viewer, "#projection", "Channel history")
    async with workspace.app(size=(120, 40), application=FrameApp) as ui:
        app, _ = ui.textual
        first = ui.selected_tab
        second = await ui.new_session()
        channel = await ui.open_channel("#projection", actor=viewer)
        modes = [first, second, channel]
        for mode in modes:
            await ui.select_tab(mode)
        await ui.select_tab(first)
        shared = app.screen.query_one("#channels-sidebar", SideBar)
        thread_bars = {mode: app.workspace_sessions.require(mode).query_one("#thread-sidebar", SideBar)
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
