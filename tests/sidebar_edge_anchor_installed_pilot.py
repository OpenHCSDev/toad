"""Click both sidebar close orders in the installed Textual and ACP workspace."""

import asyncio
import os
import shlex
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from l0a_native_installed_pilot import until
from native_session_retention_pilot import InstalledApp
from toad.widgets.side_bar import SideBar, SideBarToggle, SidebarAction, SidebarResizeHandle


class PaintedSidebarApp(InstalledApp):
    frames: list[tuple] | None = None

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if self.frames is None or self._batch_count or renderable is None:
            return
        bars = {bar.id: (bar.region.x, bar.region.width, bar.collapsed)
                for bar in screen.query(SideBar) if bar.display
                and all(ancestor.display for ancestor in bar.ancestors)}
        if len(bars) == 2:
            expected = self.sidebar_layout.resolve(
                screen.size.width, {name: state[2] for name, state in bars.items()})
            self.frames.append((bars, expected, screen.size.width))


async def click_and_check(app, pilot, bar, expected):
    app.frames = []
    assert await pilot.click(bar.query_one(SideBarToggle))
    await until(pilot, lambda: any(
        bars[bar.id][2] is expected for bars, _, _ in app.frames))
    changed = [(bars, layout, width) for bars, layout, width in app.frames
               if bars[bar.id][2] is expected]
    for bars, layout, width in changed:
        left, right = bars["channels-sidebar"], bars["thread-sidebar"]
        assert left[0] == 0, (expected, bars, layout, width)
        assert right[0] + right[1] == width, (expected, bars, layout, width)
    assert bar.collapsed is expected
    print("PAINTED_CLOSE_ORDER", bar.id, expected, changed[0][0], flush=True)
    app.frames = None


async def main():
    with TemporaryDirectory(prefix="toad-sidebar-edge-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"),
                          TOAD_TEST_ATTEMPT=root.name)
        peer = Path(__file__).with_name("acp_completion_server.py")
        agent = {"name": "Sidebar SDK peer", "identity": "sidebar-sdk",
                 "short_name": "SDK", "protocol": "acp",
                 "run_command": {"*": shlex.join([sys.executable, str(peer)])}}
        app = PaintedSidebarApp(project_dir=str(root), agent_data=agent)
        async with app.run_test(size=(110, 34)) as pilot:
            await until(pilot, lambda: app.selected_session.conversation.agent is not None
                        and app.selected_session.conversation.agent.ready)
            left = app.screen.query_one("#channels-sidebar", SideBar)
            right = app.screen.query_one("#thread-sidebar", SideBar)
            right.reveal()
            await right.wait_content_ready()
            await pilot.pause()
            assert not left.collapsed and not right.collapsed
            grip = right.query_one(SidebarResizeHandle)
            assert grip.display and grip in app.screen._compositor.visible_widgets
            assert grip.region.x == right.region.x and grip.region.width == 1
            old_width = right.region.width
            start = grip.region.x
            y = grip.region.y + 3
            assert await pilot.hover(grip, offset=(0, 3))
            assert "hover" in grip.pseudo_classes
            assert await pilot.mouse_down(grip, offset=(0, 3))
            assert not app.screen._selecting
            assert await pilot.hover(offset=(start - 5, y))
            assert not app.screen._selecting
            assert await pilot.mouse_up(offset=(start - 5, y))
            await pilot.pause()
            assert abs(right.region.width - (old_width + 5)) <= 1, (
                old_width, right.region, app.sidebar_layout.get(right.id))
            assert grip.region.x == right.region.x
            assert not grip._dragging and app.mouse_captured is None
            print("PAINTED_RIGHT_GRIP_DRAG", old_width, right.region.width, flush=True)
            await click_and_check(app, pilot, left, True)
            await click_and_check(app, pilot, left, False)
            await click_and_check(app, pilot, right, True)
            await click_and_check(app, pilot, right, False)
            for action in ("right", "right", "left", "left"):
                assert await pilot.click(left.query_one(f"#sidebar-{action}", SidebarAction))
                await pilot.pause()
                layout = app.sidebar_layout.resolve(
                    app.screen.size.width, {bar.id: bar.collapsed
                                            for bar in (left, right)})
                for bar in (left, right):
                    expected = layout.bars[bar.id]
                    assert (bar.region.x, bar.region.width) == (expected.x, expected.width), (
                        action, bar.id, bar.region, expected)
            await pilot.resize_terminal(76, 34)
            await click_and_check(app, pilot, left, True)
            await click_and_check(app, pilot, right, True)
            await click_and_check(app, pilot, left, False)
            await click_and_check(app, pilot, right, False)
            content = app.selected_session.query_one("#session-content")
            pushing_width = content.region.width
            app.sidebar_layout.float_mode(right.id)
            app.sidebar_layout_changed.publish(None)
            await pilot.pause()
            assert app.sidebar_layout.get(right.id).floating
            assert content.region.width > pushing_width, (
                "Floating must return the sidebar's width to conversation content",
                pushing_width, content.region.width)
            await click_and_check(app, pilot, left, True)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
