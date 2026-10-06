"""Real private-store menu selection and batch archive through the native App."""
import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from agent_comms.thread_status import StoppedThreadStatus, ArchivedThreadStatus, RunningThreadStatus
from runtime_fixture import ToadApp
from toad.widgets.comms_sidebar import CommsSidebar, ThreadRow, ChannelGroup
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_command_dialog import CommandDialog


async def main():
    scratch = Path('/home/ts/.cache/agent-scratch/parent-sidebar-selection-20261006')
    with tempfile.TemporaryDirectory(prefix='mounted-', dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        comms = Comms(root / 'wire', private_initial_writes=True)
        for index in range(4):
            comms.registry.declare(Thread(f'selection-{index}', frozenset({'alpha'}), str(root)), StoppedThreadStatus())
        comms.messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        app.settings.sidebar.show_stopped = True
        async with app.run_test(size=(130, 46), notifications=True) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.observation.sync()
            await pilot.pause()
            group = next(row.query_ancestor(ChannelGroup)
                         for row in sidebar.projection.channels.values() if row.target_name == '#alpha')
            await group.reveal_members()
            await pilot.pause()
            rows = [row for row in group.member_container.children if isinstance(row, ThreadRow)]
            first, second, third = rows[:3]
            original_mode = app.selected_mode
            assert await pilot.click(first, control=True)
            assert await pilot.click(third, shift=True)
            assert len(app.sidebar_state.selected_targets) == 3
            assert all(row.has_class('-selected') for row in (first, second, third))
            assert app.selected_mode == original_mode
            assert await pilot.click(second, control=True)
            assert len(app.sidebar_state.selected_targets) == 2
            selected = app.sidebar_state.selected_targets
            assert await pilot.click(first, button=3)
            async with asyncio.timeout(10):
                while not isinstance(app.screen, ContextMenu):
                    await pilot.pause()
            assert app.sidebar_state.selected_targets == selected
            menu = app.screen
            item = next(item for item in menu.query(ContextMenuItem) if item.action == 'read-target')
            assert await pilot.click(item)
            async with asyncio.timeout(10):
                while not isinstance(app.screen, CommandDialog):
                    await pilot.pause()
            dialog = app.screen
            assert dialog.definition.targets == (first.target_name, third.target_name)
            if dialog.definition.confirmation:
                await pilot.click('#command-confirmed')
            await pilot.click('#command-apply')
            await pilot.pause()
            async with asyncio.timeout(10):
                while app.thread_actions.requests:
                    await pilot.pause()
            assert await pilot.click(first, button=3)
            async with asyncio.timeout(10):
                while not isinstance(app.screen, ContextMenu):
                    await pilot.pause()
            item = next(item for item in app.screen.query(ContextMenuItem) if item.action == 'archive')
            assert await pilot.click(item)
            await pilot.pause()
            async with asyncio.timeout(10):
                while app.thread_actions.requests:
                    await pilot.pause()
            archived = comms.registry.snapshot()
            assert isinstance(archived.status(first.target_name), ArchivedThreadStatus)
            assert isinstance(archived.status(third.target_name), ArchivedThreadStatus)
            assert isinstance(archived.status(second.target_name), StoppedThreadStatus)
            # Channel and thread share selection intent and backend menu discovery.
            await sidebar.observation.sync()
            await pilot.pause()
            channel = sidebar.projection.channels['#alpha']
            survivor = next(row for row in sidebar.projection.thread_rows if row.target_name == second.target_name)
            sidebar.navigation.pointer_select(channel)
            sidebar.navigation.pointer_select(survivor, control=True)
            context = sidebar.navigation.menu_context(channel)
            assert context.targets == ('#alpha', second.target_name)
            actions = await app.preparation.run_thread(context.available_actions)
            assert actions and all(action.targets == context.targets for action in actions)
            # Availability changes after the menu was acquired: real backend
            # admission refuses this member while retaining the other success.
            fourth = next(row for row in sidebar.projection.thread_rows
                          if row.target_name == rows[3].target_name)
            sidebar.navigation.pointer_select(survivor)
            sidebar.navigation.pointer_select(fourth, control=True)
            assert await pilot.click(survivor, button=3)
            async with asyncio.timeout(10):
                while not isinstance(app.screen, ContextMenu):
                    await pilot.pause()
            comms.registry.declare(comms.registry.require(fourth.target_name), RunningThreadStatus())
            app.clear_notifications()
            item = next(item for item in app.screen.query(ContextMenuItem) if item.action == 'archive')
            assert await pilot.click(item)
            await pilot.pause()
            async with asyncio.timeout(10):
                while app.thread_actions.requests:
                    await pilot.pause()
            snapshot = comms.registry.snapshot()
            assert isinstance(snapshot.status(survivor.target_name), ArchivedThreadStatus)
            assert isinstance(snapshot.status(fourth.target_name), RunningThreadStatus)
            notifications = tuple(app._notifications)
            assert len(notifications) == 1, notifications
            assert notifications[0].severity == 'error'
            assert '1/2 completed' in notifications[0].message
            assert fourth.target_name in notifications[0].message
            # A range belongs to the displayed hierarchy, including admitted
            # rows scrolled outside the viewport. Exercise native pointer input
            # after the anchor has actually left the clipped panel.
            for index in range(60):
                comms.registry.declare(Thread(f'range-{index:02}', frozenset({'range'}), str(root)), StoppedThreadStatus())
            await sidebar.observation.sync()
            await pilot.pause()
            group = sidebar.projection.channels['#range'].query_ancestor(ChannelGroup)
            await group.reveal_members()
            await pilot.pause()
            range_rows = tuple(group.member_container.children)
            anchor, endpoint = range_rows[0], range_rows[-1]
            anchor.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert await pilot.click(anchor, button=3)
            async with asyncio.timeout(10):
                while not isinstance(app.screen, ContextMenu):
                    await pilot.pause()
            await pilot.press('escape')
            endpoint.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert not anchor.is_on_screen and endpoint.is_on_screen
            assert await pilot.click(endpoint, shift=True)
            assert tuple(item.target for item in app.sidebar_state.selected_targets) == tuple(row.target_name for row in range_rows)
            assert app.selected_mode == original_mode
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print('PASS: Ctrl toggle, Shift range, preserved right-click selection, real dialog/archive, mixed channel/thread catalog and honest partial-failure notification')


if __name__ == '__main__':
    asyncio.run(main())
