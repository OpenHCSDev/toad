"""Hidden thread/channel sidebars retain geometry until atomic activation."""

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import session_thread_name
from toad.widgets.side_bar import SideBar


class FrameApp(ToadApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = None

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if (self.frames is not None and renderable is not None and not self._batch_count
                and screen is self.screen):
            sidebar = screen.query_one_optional("#channels-sidebar", SideBar)
            if sidebar is not None:
                self.frames.append((self.current_mode, sidebar.collapsed, sidebar.size.width,
                                    sidebar.query_one("#sidebar-panels").display))
        return result


async def main():
    with tempfile.TemporaryDirectory(prefix="sidebar-projection-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        me = session_thread_name(root)
        comms.register(Thread(me, frozenset({"fixture"}), str(root), pid=os.getpid()))
        comms.set_channel("#projection", frozenset({"fixture"}))
        comms.send(me, "#projection", "Channel history")
        app = FrameApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            first = app.current_mode
            second = (await app.new_session_screen(app.get_main_screen)).mode_name
            channel = await app.open_comms_session(owner_mode=first, project_path=root,
                                                   me=me, target="#projection", kind="channel")
            modes = [first, second, channel]
            for mode in modes:
                await app.switch_mode(mode)
                await pilot.pause()
            await app.switch_mode(first)
            await pilot.pause()
            sidebars = {mode: app.get_screen_stack(mode)[0].query_one("#channels-sidebar", SideBar)
                        for mode in modes}
            sidebars[first].reveal()
            await pilot.pause()
            hidden_styles = {mode: sidebars[mode].styles.get_rules() for mode in (second, channel)}
            hidden_layouts = {mode: sidebars[mode]._layout_updates for mode in (second, channel)}
            right_states = {mode: app.get_screen_stack(mode)[0].query_one("#thread-sidebar", SideBar).collapsed
                            for mode in modes}
            sidebars[first].toggle()
            await pilot.pause()
            assert all(sidebar.collapsed for sidebar in sidebars.values())
            for mode in (second, channel):
                assert sidebars[mode].styles.get_rules() == hidden_styles[mode]
                assert sidebars[mode]._layout_updates == hidden_layouts[mode]
            sidebars[first].toggle()
            await pilot.pause()
            for mode in (second, channel):
                assert sidebars[mode].styles.get_rules() == hidden_styles[mode]
                assert sidebars[mode]._layout_updates == hidden_layouts[mode]

            # A one-way hidden collapse must be applied before its first frame,
            # for both native thread and channel screens.
            sidebars[first].toggle()
            await pilot.pause()
            app.frames = []
            for mode in (second, channel):
                await app.switch_mode(mode)
                await pilot.pause()
                frames = [frame for frame in app.frames if frame[0] == mode]
                assert frames and all(collapsed and width == 3 and not panels
                                      for _, collapsed, width, panels in frames), frames
            app.frames = None
            sidebars[channel].reveal()
            await pilot.pause()
            app.frames = []
            await app.switch_mode(first)
            await pilot.pause()
            frames = [frame for frame in app.frames if frame[0] == first]
            assert frames and all(not collapsed and width > 3 and panels
                                  for _, collapsed, width, panels in frames), frames
            for mode in modes:
                assert app.get_screen_stack(mode)[0].query_one("#thread-sidebar", SideBar).collapsed == right_states[mode]
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("sidebar projection: hidden round trips retain geometry; first activated thread/channel frames match intent")


if __name__ == "__main__":
    asyncio.run(main())
