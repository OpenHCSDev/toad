"""Arrow clicks follow spatial neighbors rather than fixed move/swap actions."""

import asyncio
import os
import tempfile
from pathlib import Path

from runtime_fixture import ToadApp

from toad.widgets.side_bar import SideBar, SidebarAction


def arrows(bar: SideBar) -> list[str]:
    return [button.render().plain for button in bar.query(SidebarAction)
            if button.display and button.action != "float"]


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-direction-") as directory:
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
            channels = app.screen.query_one("#channels-sidebar", SideBar)
            thread = app.screen.query_one("#thread-sidebar", SideBar)
            thread.reveal()
            await pilot.pause()

            async def click(bar: SideBar, label: str) -> None:
                button = next(button for button in bar.query(SidebarAction)
                              if button.display and button.render().plain == label)
                assert await pilot.click(button)
                await pilot.pause()

            assert arrows(channels) == ["──>"] and arrows(thread) == ["<──"]
            await click(thread, "<──")
            assert not channels.right and not thread.right
            assert channels.region.right == thread.region.x
            assert arrows(channels) == ["──>"], "Wall-adjacent bar must have only the inward arrow"
            assert arrows(thread) == ["<──", "──>"]

            await click(channels, "──>")
            assert not channels.right and not thread.right, "Inward click must swap, not cross the conversation"
            assert thread.region.right == channels.region.x
            assert arrows(thread) == ["──>"] and arrows(channels) == ["<──", "──>"]
            await click(channels, "<──")
            assert channels.region.right == thread.region.x
            await click(thread, "──>")
            assert thread.right and not channels.right

            await click(channels, "──>")
            assert channels.right and thread.right
            assert channels.region.right == thread.region.x
            assert arrows(thread) == ["<──"] and arrows(channels) == ["<──", "──>"]
            await click(thread, "<──")
            assert channels.right and thread.right
            assert thread.region.right == channels.region.x
            assert arrows(channels) == ["<──"] and arrows(thread) == ["<──", "──>"]
            await click(thread, "──>")
            assert channels.region.right == thread.region.x

            # Float and a collapsed neighbor do not change the arrow policy.
            await click(thread, "Float")
            channels.toggle()
            await pilot.pause()
            assert arrows(thread) == ["<──"]
            await click(thread, "<──")
            assert thread.right and channels.right
            assert thread.region.right == channels.region.x
            assert arrows(thread) == ["<──", "──>"]
            channels.reveal()
            await pilot.pause()
            assert arrows(channels) == ["<──"]
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("directional sidebar arrows: walls, inward swaps, outward swaps, cross-center moves, Float/collapse")


if __name__ == "__main__":
    asyncio.run(main())
