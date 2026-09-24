"""Mounted first-frame alignment across collapsed and expanded owner tabs."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from textual.worker import WorkerCancelled

from toad.app import ToadApp
from toad.screens.main import MainScreen
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import SideBar, TabHistoryControls


def aligned(screen: MainScreen, expected: int | None = None) -> None:
    left = screen.query_one("#channels-sidebar", SideBar)
    tabs = screen.query_one(SessionsTabs)
    conversation = screen.conversation
    assert conversation.region.x == left.region.right, (
        tabs.region,
        conversation.region,
        left.region,
        left.collapsed,
        left.styles.width,
        screen.query_one("#tab-navigation-header").styles.padding,
    )
    if expected is not None:
        assert left.region.width == expected, (left.region, expected)
    else:
        assert 18 <= left.region.width <= screen.size.width // 2
    controls = screen.query_one(TabHistoryControls)
    assert (
        controls.region.x == 0
        and tabs.region.x == controls.region.right
        and tabs.region.right == screen.region.right
    ), (
        tabs.region,
        controls.region,
        screen.region,
    )


async def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="toad-layout-", dir="/dev/shm"))
    os.environ.update(
        AGENT_COMMS_ROOT=str(root / "wire"),
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_STATE_HOME=str(root / "state"),
        XDG_DATA_HOME=str(root / "data"),
    )
    wire(root / "wire").register(
        Thread(root.name, frozenset(), str(root), pid=os.getpid())
    )
    app = ToadApp(project_dir=str(root))
    width = int(os.getenv("TOAD_LAYOUT_WIDTH", "120"))
    expanded = width * 40 // 100
    async with app.run_test(size=(width, 44)) as pilot:
        await pilot.pause()
        first_mode = app.current_mode
        first = app.screen
        assert isinstance(first, MainScreen)
        aligned(first, expanded)  # First visible frame, not a follow-up sidebar tick.
        alternate = 76 if width == 120 else 120
        await pilot.resize_terminal(alternate, 44)
        aligned(first, alternate * 40 // 100)
        await pilot.resize_terminal(width, 44)
        aligned(first, expanded)
        first.query_one("Prompt").text = "retain draft"
        first_right = first.query_one("#thread-sidebar", SideBar)
        assert first_right.collapsed
        first_right.toggle()
        await pilot.pause()
        assert not first_right.collapsed
        aligned(first)

        first_left = first.query_one("#channels-sidebar", SideBar)
        first_left.toggle()
        await pilot.pause()
        assert first_left.collapsed
        aligned(first, 3)
        first_left.toggle()
        await pilot.pause()
        aligned(first)
        first_left.toggle()
        await pilot.pause()
        aligned(first, 3)

        second_mode = (await app.new_session_screen(lambda: MainScreen(root))).mode_name
        assert second_mode != first_mode
        second = app.screen
        assert isinstance(second, MainScreen)
        aligned(second, 3)
        assert second.query_one("#thread-sidebar", SideBar).collapsed
        assert not first_right.collapsed  # Right sidebar is owner-local.

        await app.switch_mode(first_mode)
        aligned(first, 3)  # No stale header padding on first frame after switch.
        assert first.query_one("Prompt").text == "retain draft"
        first.query_one("#channels-sidebar", SideBar).toggle()
        await pilot.pause()
        aligned(first)
        await app.switch_mode(second_mode)
        aligned(second, expanded)
        assert second.query_one("#thread-sidebar", SideBar).collapsed
        await app.switch_mode(first_mode)
        aligned(first)

        app.workers.cancel_all()
        stopped = await asyncio.gather(
            *(worker.wait() for worker in tuple(app.workers)), return_exceptions=True
        )
        assert all(
            not isinstance(result, BaseException) or isinstance(result, WorkerCancelled)
            for result in stopped
        ), stopped
    print("mounted first-frame two-owner expanded/collapsed tab alignment OK")


if __name__ == "__main__":
    asyncio.run(main())
