"""Pointer menus preserve sidebar position; keyboard rows still scroll normally."""
import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad.widgets.comms_sidebar import CommsSidebar, ThreadRow
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.side_bar import SidebarViewport


async def main():
    scratch = Path('/home/ts/.cache/agent-scratch/parent-sidebar-context-20261006')
    with tempfile.TemporaryDirectory(prefix='mounted-', dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'),
                          TOAD_TEST_ATTEMPT='sidebar-context-scroll-20261006')
        comms = Comms(root / 'wire', private_initial_writes=True)
        for index in range(32):
            comms.registry.declare(Thread(f'context-row-{index:02}', frozenset({'alpha'}), str(root)))
        comms.messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        app.settings.sidebar.show_stopped = True
        async with app.run_test(size=(113, 34)) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            # Setup uses the existing canonical observer; expose a refused read
            # rather than waiting for a swallowed asynchronous setup failure.
            await sidebar.observation.sync()
            await pilot.pause()
            async with asyncio.timeout(10):
                while not list(sidebar.query(ThreadRow)):
                    await pilot.pause()
            viewport = sidebar.query_ancestor(SidebarViewport)
            rows = list(sidebar.query(ThreadRow))
            row = rows[len(rows) // 2]
            viewport.scroll_to(y=viewport.scroll_y + row.region.y - viewport.content_region.y + 1,
                               animate=False, immediate=True, force=True)
            await pilot.pause()
            visible = row.region.intersection(viewport.content_region)
            assert visible and visible.height < row.region.height, (row.region, visible)
            selected = app.selected_mode
            prompt = app.selected_session.conversation.prompt.prompt_text_area
            prompt.focus(scroll_visible=False)
            await pilot.pause()
            before = viewport.scroll_y
            cell = visible.offset - row.region.offset
            assert await pilot.click(row, offset=tuple(cell), button=3)
            async with asyncio.timeout(10):
                while not isinstance(app.screen, ContextMenu):
                    await pilot.pause()
            assert viewport.scroll_y == before, (before, viewport.scroll_y)
            await pilot.press('escape')
            await pilot.pause()
            assert viewport.scroll_y == before, (before, viewport.scroll_y)
            assert app.selected_mode == selected
            assert app.focused is prompt
            # Keyboard traversal still owns row focus and scroll visibility.
            row.focus()
            await pilot.pause()
            assert app.focused is row
            assert row.region.y >= viewport.content_region.y
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print('PASS: real right-click menu preserves clipped row/sidebar and composer focus; keyboard row focus still reveals it')


if __name__ == '__main__':
    asyncio.run(main())
