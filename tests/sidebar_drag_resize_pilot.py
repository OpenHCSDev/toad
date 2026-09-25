"""Real pointer/keyboard resize from either edge, with hover and slider parity."""

import asyncio
import os
import tempfile
from pathlib import Path

from runtime_fixture import ToadApp

from toad.widgets.side_bar import (
    SideBar, SideBarToggle, SidebarAction, SidebarResizeHandle, SidebarSlider, TabHistoryControls,
)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-drag-resize-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            bar = app.screen.query_one("#channels-sidebar", SideBar)
            for side in ("left", "right"):
                app.sidebar_layout.move("channels-sidebar", side)
                app.sidebar_layout.width("channels-sidebar", 30)
                app.sidebar_layout_changed.publish(None)
                await pilot.pause()
                slider = bar.query_one("#sidebar-width-slider", SidebarSlider)
                handle = bar.query_one(SidebarResizeHandle)
                toggle = bar.query_one(SideBarToggle)
                assert (toggle.region.right == handle.region.x if side == "left"
                        else toggle.region.x == handle.region.right), (side, toggle.region, handle.region)
                direction = 1 if side == "left" else -1
                assert slider.reversed == (side == "right")
                for theme in ("ansi-dark", "textual-dark"):
                    app.theme = theme
                    app.screen.conversation.prompt.focus()
                    await pilot.hover(app.screen.query_one(TabHistoryControls))
                    await pilot.pause()
                    normal = handle.styles.color
                    assert await pilot.hover(handle, offset=(0, 3))
                    await pilot.pause()
                    assert handle.styles.color != normal and "hover" in handle.pseudo_classes
                    for selector in (f"#sidebar-{'right' if side == 'left' else 'left'}", "#sidebar-float"):
                        button = bar.query_one(selector, SidebarAction)
                        normal = button.styles.background
                        assert await pilot.hover(button)
                        await pilot.pause()
                        assert button.styles.background != normal
                        await pilot.hover(handle, offset=(0, 3))
                start = handle.region.x
                y = handle.region.y + 3
                old_width = bar.size.width
                assert await pilot.mouse_down(handle, offset=(0, 3))
                await pilot.hover(offset=(start + direction * 12, y))
                await pilot.mouse_up(offset=(start + direction * 12, y))
                await pilot.pause()
                assert bar.size.width == old_width + 12, (side, bar.size, old_width)
                assert slider.value == app.sidebar_layout.get(bar.id).width_percent == 40
                assert not handle._dragging and app.mouse_captured is None

                # The physical arrow keys and slider endpoints mirror as well.
                slider.focus()
                await pilot.press("right" if side == "left" else "left")
                assert slider.value == 41
                await pilot.press("left" if side == "left" else "right")
                assert slider.value == 40
                inward = slider.size.width - 1 if side == "left" else 0
                assert await pilot.click(slider, offset=(inward, 0))
                await pilot.pause()
                assert slider.value == 50 and bar.size.width == 60, (side, slider.value, bar.region)
                outward = 4 if side == "left" else slider.size.width - 1
                assert await pilot.click(slider, offset=(outward, 0))
                await pilot.pause()
                assert slider.value == 15 and bar.size.width == 18
                assert handle.region.x == (bar.region.right - 1 if side == "left" else bar.region.x)
                bar.toggle()
                await pilot.pause()
                assert not handle.display
                assert toggle.region == bar.region
                bar.reveal()
                await pilot.pause()
                assert handle.display
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("edge drag and mirrored slider: left/right, ANSI/RGB hover, pointer capture, collapse")


if __name__ == "__main__":
    asyncio.run(main())
