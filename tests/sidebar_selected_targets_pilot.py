"""Real private-store menu selection and batch archive through the native App."""
import asyncio
import json
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


async def process_batch():
    """Real menu start/stop of two idle workers, including channel overlap."""
    from runtime_fixture import private_native_wire
    root = Path(os.environ['SELECTION_PROCESS_EVIDENCE'])
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for key in tuple(os.environ):
        if key.startswith('AGENT_COMMS_'):
            del os.environ[key]
    os.environ.update(TOAD_TEST_ATTEMPT=str(root),
                      XDG_CONFIG_HOME=str(root / 'config'),
                      XDG_STATE_HOME=str(root / 'state'),
                      XDG_DATA_HOME=str(root / 'data'),
                      XDG_CACHE_HOME=str(root / 'cache'),
                      PI_CODING_AGENT_DIR=str(root / 'pi'),
                      AGENT_COMMS_AGENT_BIN='pi',
                      AGENT_COMMS_AGENT_ARGS='--no-extensions --no-skills --no-context-files',
                      AGENT_COMMS_AGENT_MODELS='selected-offline/fixture')
    comms = private_native_wire(root / 'wire')
    comms.owners.pin_private_nk_launch(
        comms.root, os.environ['AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID'],
        Path(os.environ['AC_NATIVE_COPIED_PACKAGE']))
    names = ('batch-alpha', 'batch-beta')
    for name in names:
        comms.registry.declare(Thread(name, frozenset({'batch'}), str(root)), StoppedThreadStatus())
    app = ToadApp(project_dir=str(root))
    app.settings.sidebar.show_stopped = True

    async def until(pilot, condition):
        async with asyncio.timeout(30):
            while not condition():
                await pilot.pause(.02)

    async def menu(pilot, row, operation):
        row.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert await pilot.click(row, button=3)
        await until(pilot, lambda: isinstance(app.screen, ContextMenu) and app.screen.is_mounted)
        item = next(item for item in app.screen.query(ContextMenuItem) if item.action == operation)
        assert await pilot.click(item)
        await until(pilot, lambda: not app.thread_actions.requests)

    async with app.run_test(size=(130, 46), notifications=True) as pilot:
        await app.selected_session.wait_content_ready()
        app.workspace_chrome.channels.reveal()
        await app.workspace_chrome.channels.wait_content_ready()
        await pilot.pause()
        sidebar = app.screen.query_one(CommsSidebar)
        await sidebar.observation.sync()
        await until(pilot, lambda: '#batch' in sidebar.projection.channels)
        group = sidebar.projection.channels['#batch'].query_ancestor(ChannelGroup)
        await group.reveal_members()
        await pilot.pause()
        rows = tuple(group._members[name] for name in names)
        # Channel plus its individually selected members execute each owner once.
        for row in (group.row, *rows):
            row.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert await pilot.click(row, control=True)
        await menu(pilot, rows[0], 'start')
        await until(pilot, lambda: all(comms.registry.require(name).process_alive for name in names))
        originals = tuple(comms.registry.require(name).process_identity for name in names)
        assert all(identity is not None for identity in originals)
        assert len({identity.pid for identity in originals}) == 2
        await sidebar.observation.sync()
        await pilot.pause()
        assert all(group._members[name] is row for name, row in zip(names, rows))
        await menu(pilot, rows[0], 'stop')
        await until(pilot, lambda: all(not identity.alive() for identity in originals))
        assert all(comms.registry.status(name).stopped for name in names)
        assert app._exception is None
        (root / 'result.json').write_text(json.dumps({
            'started': names, 'original_processes': [dict(pid=identity.pid, start_time=identity.start_time)
                                                   for identity in originals],
            'stopped_and_absent': True, 'row_identity_preserved': True,
            'selected_channel_member_overlap': True, 'submitted_inputs': 0,
        }, indent=2) + '\n')
    print('PASS: real native menu starts/stops two idle workers once despite channel/member overlap', flush=True)


async def main():
    scratch = Path('/home/ts/.cache/agent-scratch/parent-sidebar-selection-20261006')
    scratch.mkdir(parents=True, exist_ok=True)
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
            await app.selected_session.wait_content_ready()
            app.workspace_chrome.channels.reveal()
            await app.workspace_chrome.channels.wait_content_ready()
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
            scroll = sidebar.navigation.scroll_container.scroll_y
            assert await pilot.click(channel, button=3)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
                    await pilot.pause()
            assert sidebar.navigation.scroll_container.scroll_y == scroll
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
            await app.selected_session.wait_content_ready()
            app.workspace_chrome.channels.reveal()
            await app.workspace_chrome.channels.wait_content_ready()
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
            assert all(not snapshot.status(name).active for name in ('batch-alpha', 'batch-beta'))
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print('PASS: installed native multi-channel menu, shared disposition dialog, both confirmations, original tag removal, refreshed channel rows and preserved threads')


async def same_thread_memberships():
    """Native rows share a thread owner but retain independent channel pins."""
    scratch = Path('/home/ts/.cache/agent-scratch/selected-memberships-20261007')
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mounted-', dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        comms = Comms(root / 'wire', private_initial_writes=True)
        comms.registry.declare(Thread('shared-member', frozenset({'alpha', 'beta'}), str(root)),
                               StoppedThreadStatus())
        comms.messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        app.settings.sidebar.show_stopped = True
        async with app.run_test(size=(130, 46), notifications=True) as pilot:
            await app.selected_session.wait_content_ready()
            app.workspace_chrome.channels.reveal()
            await app.workspace_chrome.channels.wait_content_ready()
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.observation.sync()
            rows = []
            for name in ('#alpha', '#beta'):
                group = sidebar.projection.channels[name].query_ancestor(ChannelGroup)
                await group.reveal_members()
                await pilot.pause()
                rows.append(next(row for row in group.member_container.children
                                 if isinstance(row, ThreadRow) and row.target_name == 'shared-member'))
            assert await pilot.click(rows[0])
            assert await pilot.click(rows[1], control=True)
            assert len(app.sidebar_state.selected_targets) == 2
            assert all(row.has_class('-selected') for row in rows)
            context = sidebar.navigation.menu_context(rows[0])
            assert context.targets == ('shared-member',)
            assert context.channel == {'shared-member': ('#alpha', '#beta')}
            scroll = sidebar.navigation.scroll_container.scroll_y
            assert await pilot.click(rows[0], button=3)
            async with asyncio.timeout(10):
                while not (isinstance(app.screen, ContextMenu) and app.screen.is_mounted):
                    await pilot.pause()
            assert sidebar.navigation.scroll_container.scroll_y == scroll
            item = next(item for item in app.screen.query(ContextMenuItem) if item.action == 'pin-thread')
            assert await pilot.click(item)
            async with asyncio.timeout(10):
                while app.thread_actions.requests or any(
                    comms.channels.catalog.read().pinned_threads(name) != {'shared-member'}
                    for name in ('#alpha', '#beta')):
                    await pilot.pause()
            assert comms.registry.require('shared-member').tags == frozenset({'alpha', 'beta'})
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print('PASS: native Ctrl-selected same thread in two channels, both pins preserved, right-click scroll unchanged')


if __name__ == '__main__':
    asyncio.run(process_batch() if '--process-batch' in sys.argv else
                same_thread_memberships() if '--same-thread-memberships' in sys.argv else
                multi_channel_removal() if '--multi-channel-removal' in sys.argv else main())
