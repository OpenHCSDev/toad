"""Real private-store menu selection and batch archive through the native App."""
import asyncio
import os
import sys
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
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
                    await pilot.pause()
            assert app.sidebar_state.selected_targets == selected
            menu = app.screen
            item = next(item for item in menu.query(ContextMenuItem) if item.action == 'read-target')
            assert await pilot.click(item)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, CommandDialog) and app.screen.is_mounted):
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
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
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
            scroll = tuple(panel.scroll_y for panel in sidebar.navigation.scroll_containers)
            assert await pilot.click(channel, button=3)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
                    await pilot.pause()
            assert tuple(panel.scroll_y for panel in sidebar.navigation.scroll_containers) == scroll
            await pilot.press('escape')
            assert await pilot.click(survivor, control=True)
            context = sidebar.navigation.menu_context(channel)
            assert context.targets == ('#alpha', second.target_name)
            actions = await app.preparation.run_thread(context.available_actions)
            assert actions and all(action.targets == context.targets for action in actions)
            # Availability changes after the menu was acquired: real backend
            # admission refuses this member while retaining the other success.
            fourth = next(row for row in sidebar.projection.thread_rows
                          if row.target_name == rows[3].target_name)
            # Right-click preserves this mixed selection. Remove its channel
            # through the same Ctrl-toggle before acquiring a two-thread menu.
            assert await pilot.click(channel, control=True)
            assert tuple(item.target for item in app.sidebar_state.selected_targets) == (survivor.target_name,)
            assert await pilot.click(fourth, control=True)
            assert tuple(item.target for item in app.sidebar_state.selected_targets) == (survivor.target_name, fourth.target_name)
            assert await pilot.click(survivor, button=3)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
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
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
                    await pilot.pause()
            await pilot.press('escape')
            endpoint.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            visible = app.screen._compositor.visible_widgets
            assert anchor not in visible and endpoint in visible
            assert await pilot.click(endpoint, shift=True)
            assert tuple(item.target for item in app.sidebar_state.selected_targets) == tuple(row.target_name for row in range_rows)
            # Channel endpoints use the same admitted hierarchy. Expanded
            # member rows between them legitimately belong to a Shift range.
            channel = sidebar.projection.channels['#alpha']
            channel.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert await pilot.click(channel, button=3)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
                    await pilot.pause()
            await pilot.press('escape')
            endpoint = sidebar.projection.channels['#range']
            endpoint.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            admitted = sidebar.projection.rows
            start, end = sorted((admitted.index(channel), admitted.index(endpoint)))
            expected = tuple(row.target_name for row in admitted[start:end + 1])
            assert await pilot.click(endpoint, shift=True)
            assert tuple(item.target for item in app.sidebar_state.selected_targets) == expected
            assert channel.has_class('-selected') and endpoint.has_class('-selected')
            assert app.selected_mode == original_mode

            # A channel archive is the catalog's reversible visibility state,
            # not an archive of its threads. Exercise the actual single-target
            # menu and confirmation, then its published sidebar removal.
            assert await pilot.click(channel)
            await pilot.pause()
            await sidebar.observation.sync()
            await pilot.pause()
            channel = sidebar.projection.channels['#alpha']
            channel.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            original_registry = comms.registry.snapshot()
            assert await pilot.click(channel, button=3)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
                    await pilot.pause()
            item = next(item for item in app.screen.query(ContextMenuItem)
                        if item.action == 'archive-channel')
            assert await pilot.click(item)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, CommandDialog) and app.screen.is_mounted):
                    await pilot.pause()
            assert app.screen.definition.targets == ('#alpha',)
            await pilot.click('#command-confirmed')
            await pilot.click('#command-apply')
            async with asyncio.timeout(10):
                while app.thread_actions.requests or '#alpha' in sidebar.projection.channels:
                    await pilot.pause()
            assert comms.channels.catalog.read().resolve('#alpha').archived
            assert comms.registry.snapshot() == original_registry
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print('PASS: native thread/channel Ctrl toggle and Shift range, preserved right-click selection/scroll, real dialog/archive, mixed catalog and honest partial-failure notification')


async def multi_channel_removal():
    """Apply the original disposition dialog to two real private channel tags."""
    scratch = Path('/home/ts/.cache/agent-scratch/parent-tag-batch-installed-20261007')
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mounted-', dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        comms = Comms(root / 'wire', private_initial_writes=True)
        for name, tag in (('batch-alpha', 'alpha'), ('batch-beta', 'beta')):
            comms.registry.declare(Thread(name, frozenset({tag}), str(root)), StoppedThreadStatus())
        comms.messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        app.settings.sidebar.show_stopped = True
        async with app.run_test(size=(130, 46), notifications=True) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.observation.sync()
            await pilot.pause()
            alpha = sidebar.projection.channels['#alpha']
            beta = sidebar.projection.channels['#beta']
            assert await pilot.click(alpha, control=True)
            assert await pilot.click(beta, control=True)
            assert tuple(item.target for item in app.sidebar_state.selected_targets) == ('#alpha', '#beta')
            assert await pilot.click(alpha, button=3)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
                    await pilot.pause()
            item = next(item for item in app.screen.query(ContextMenuItem) if item.action == 'delete-tag')
            assert await pilot.click(item)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, CommandDialog) and app.screen.is_mounted):
                    await pilot.pause()
            dialog = app.screen
            assert dialog.definition.targets == ('#alpha', '#beta')
            assert 'Remove #alpha' in dialog.definition.confirmation
            assert 'Remove #beta' in dialog.definition.confirmation
            await pilot.click('#command-confirmed')
            await pilot.click('#command-apply')
            async with asyncio.timeout(10):
                while app.thread_actions.requests or any(
                        name in sidebar.projection.channels for name in ('#alpha', '#beta')):
                    await pilot.pause()
            snapshot = comms.registry.snapshot()
            assert snapshot.require('batch-alpha').tags == frozenset()
            assert snapshot.require('batch-beta').tags == frozenset()
            assert all(not status.active for status in snapshot.statuses.values())
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print('PASS: installed native multi-channel menu, shared disposition dialog, both confirmations, original tag removal, refreshed channel rows and preserved threads')


if __name__ == '__main__':
    asyncio.run(multi_channel_removal() if '--multi-channel-removal' in sys.argv else main())
