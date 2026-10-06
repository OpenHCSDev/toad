"""One installed App/menu and CLI journey on the same owned private bus.

No provider, public bus or native input. Imports product code from its installed
wheel; the existing pilot controls native widgets and the original backend CLI.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import threading

from agent_comms.channels import SavedView, ViewKind, ViewPredicate, AnyOfMatch
from agent_comms.cli_commands import CliCommand
from agent_comms.channel_management import ArchiveThreadsTagDisposition, DeleteThreadsTagDisposition, DeleteExclusiveInactiveThreadsTagDisposition
from agent_comms.field_codec import FieldCodec
from agent_comms.thread_status import StoppedThreadStatus
from agent_comms.threads import Thread
from textual.widgets import Checkbox, Input, Select, TextArea
from toad.screens.comms import CommsScreen
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_command_dialog import CommandDialog
from runtime_fixture import ToadApp, private_native_wire, wait_channel_roster
from saved_state_user_journey_pilot import reveal_thread_row


async def until(pilot, predicate, *, failure_prefix=None, native_wait=False):
    try:
        async with asyncio.timeout(15):
            while not predicate():
                await pilot.pause(.025)
    except TimeoutError:
        if failure_prefix is not None:
            import runpy
            diagnostic = native_wait and os.environ.get('TOAD_START_FAILURE_GDB') == '1'
            capture = runpy.run_path(Path(__file__).parents[1] / 'tools/performance/capture_state.py')['capture']
            capture(expected_pid=os.getpid(), output_prefix=failure_prefix,
                    native_process_output=(Path(os.environ['TOAD_NATIVE_WAIT_OUTPUT']) / 'startup-processes.json')
                    if diagnostic else None)
            if diagnostic:
                import signal
                signal.raise_signal(signal.SIGTRAP)
        raise


async def command(root, *arguments):
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'agent_comms.cli', '--root', str(root), *arguments,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (arguments, stdout.decode(), stderr.decode())
    return json.loads(stdout)


async def open_menu(app, pilot, row):
    from toad.widgets.comms_sidebar import CommsSidebar
    # A completed backend action may still have a pending roster publication.
    # Reconcile it through the original observer before acquiring pointer geometry.
    await row.query_ancestor(CommsSidebar).observation.sync()
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    # Native visibility admits a clipped region, not necessarily the widget's
    # top-left cell. Acquire the pointer from that original published geometry.
    screen = app.screen
    geometry = screen._compositor.visible_widgets.get(row)
    assert geometry is not None, ("Menu row has no published geometry", row.target_name)
    bounds, clip = geometry
    exposed = bounds.intersection(clip).intersection(screen.size.region)
    assert exposed, ("Menu row has no exposed cells", row.target_name, bounds, clip)
    cell = exposed.offset
    hit, _ = screen.get_widget_at(*cell)
    assert hit is row, ("Menu cell belongs to another native widget", row.target_name, cell, hit)
    clicked = await pilot.click(row, button=3,
        offset=(cell.x - row.region.x, cell.y - row.region.y))
    assert clicked, ("Native menu click missed", row.target_name, bounds, clip, cell,
                     row.is_attached, screen._compositor.visible_widgets.get(row))
    await until(pilot, lambda: isinstance(app.screen, ContextMenu) and app.screen.is_mounted)
    return {item.action: item for item in app.screen.query(ContextMenuItem)}


async def choose(app, pilot, row, operation, fields, evidence):
    menu = await open_menu(app, pilot, row)
    assert operation in menu, tuple(menu)
    assert await pilot.click(menu[operation])
    await until(pilot, lambda: not isinstance(app.screen, ContextMenu) and app.screen.is_mounted
                and (isinstance(app.screen, CommandDialog) or not app.thread_actions.pending),
                failure_prefix=evidence / (operation + '-completion-failure'), native_wait=operation == 'start')
    if not isinstance(app.screen, CommandDialog):
        assert not fields, (operation, fields)
        return
    dialog = app.screen
    for key, value in fields.items():
        editor = dialog.query_one('#command-field-' + key.replace('_', '-'))
        if isinstance(editor, Select):
            # Select's container delegates input to its native current/overlay
            # children; use its declared keyboard selection instead of treating
            # a container hit as proof that its child was not clicked.
            choices = next(item.choices for item in dialog.definition.editable_fields if item.name == key)
            index = next(index for index, (_, declared) in enumerate(choices) if declared == value)
            editor.focus()
            await pilot.press('enter', 'home', *('down',) * index, 'enter')
            assert editor.value == value
        elif isinstance(editor, TextArea):
            assert await pilot.click(editor)
            editor.text = value
        else:
            assert await pilot.click(editor)
            assert isinstance(editor, Input)
            editor.value = value
    if dialog.query_one('#command-confirmed', Checkbox).display:
        assert await pilot.click('#command-confirmed')
    app.save_screenshot(str(evidence / (operation + '-review.svg')))
    if type(app._driver).__name__ == 'LinuxDriver':
        assert os.environ['DISPLAY'] != ':0'
        await pilot.pause(.1)
        process = await asyncio.create_subprocess_exec('import', '-display', os.environ['DISPLAY'],
            '-window', 'root', str(evidence / (operation + '-review.png')))
        assert await process.wait() == 0
    assert await pilot.click('#command-apply')
    await until(pilot, lambda: not isinstance(app.screen, CommandDialog) and not app.thread_actions.pending)


async def open_channel(app, pilot, name):
    sidebar = await wait_channel_roster(app, pilot, name)
    row = sidebar.projection.channels[name]
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row)
    await until(pilot, lambda: isinstance(app.selected_session, CommsScreen)
                and app.selected_session.target == name)
    await app.selected_session.wait_content_ready()
    chat = app.selected_session.query_one(CommsChatView)
    await until(pilot, lambda: chat.agent_ready)
    return chat


async def slash(chat, pilot, text):
    editor = chat.prompt.prompt_text_area
    editor.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(editor)
    # The completed no-argument command has no fuzzy command selection to
    # dismiss. Escape on an ordinary channel composer navigates to its agent.
    editor.insert(text + ' ')
    await pilot.pause()
    await pilot.press('enter')

async def mounted_layers(app, pilot):
    from toad.widgets.comms_sidebar import CommsSidebar
    screen = app.screen
    child = screen.query_one(CommsSidebar)
    before = child.layers
    original = screen.styles.inline.get_rule('layers')
    try:
        for layers in (('base', 'controls', 'controls'), ()):
            screen.styles.layers = layers
            await pilot.pause()
            assert child.layers == layers
    finally:
        screen.styles.set_rule('layers', original)
        screen.refresh(layout=True)
    await pilot.pause()
    assert child.layers == before


async def select_rows(app, pilot, rows, evidence):
    """Use original pointer admission, preserving the row's channel context."""
    from toad.widgets.comms_sidebar import CommsSidebar
    sidebar = rows[0].query_ancestor(CommsSidebar)

    def record(step, row):
        # Witness original admission and selection; this never sets UI state.
        with (evidence / 'selection-transitions.log').open('a') as stream:
            stream.write(json.dumps({
                'step': step,
                'input': FieldCodec.encode(sidebar.navigation.selection_for(row)),
                'expected': FieldCodec.encode(tuple(sidebar.navigation.selection_for(item) for item in rows)),
                'state': FieldCodec.encode(app.sidebar_state),
                'projection': FieldCodec.encode(tuple(sidebar.navigation.selection_for(item) for item in sidebar.projection.rows)),
                'navigation_restoring': sidebar.navigation.restoring,
                'observation_pending': sidebar.observation.pending,
                'input_attached': row.is_attached,
                'input_visible': row in app.screen._compositor.visible_widgets,
            }) + '\n')

    record('before-menu', rows[0])
    await open_menu(app, pilot, rows[0])
    await pilot.press('escape')
    await sidebar.observation.sync()
    await pilot.pause()
    record('after-menu-dismiss', rows[0])
    for identity in tuple(app.sidebar_state.selected_targets):
        if identity != sidebar.navigation.selection_for(rows[0]):
            previous = next(row for row in sidebar.projection.rows
                            if sidebar.navigation.selection_for(row) == identity)
            previous.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            record('before-remove', previous)
            assert await pilot.click(previous, control=True)
            record('after-remove', previous)
    for row in rows[1:]:
        row.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        record('before-add', row)
        assert await pilot.click(row, control=True)
        record('after-add', row)
    record('before-exact-assertion', rows[0])
    assert tuple(item.target for item in app.sidebar_state.selected_targets) == tuple(row.target_name for row in rows)


async def selected_target_actions(app, pilot, comms, project, base, checks):
    """Real native menus and original private storage, without native launches."""
    from agent_comms.thread_status import ArchivedThreadStatus

    cohort = ('batch-a', 'batch-b', 'batch-c')
    source = base / 'batch-a.jsonl'
    source.write_text(json.dumps({'type': 'message', 'message': {
        'role': 'assistant', 'content': [{'type': 'text', 'text': 'Private saved batch reply'}],
    }}) + '\n')
    for name in cohort:
        comms.registry.declare(Thread(name, frozenset({'batch'}), str(project),
            session_file=str(source) if name == 'batch-a' else None), StoppedThreadStatus())
    comms.threads.restore_stopped(comms.registry.snapshot(), cohort)
    sidebar = await wait_channel_roster(app, pilot, '#batch')
    rows = [await reveal_thread_row(app, pilot, name, '#batch') for name in cohort]
    # Native Shift follows the admitted projection, not fixture declaration order.
    ordered_cohort = tuple(row.target_name for row in sidebar.projection.rows if row in rows)
    assert len(ordered_cohort) == len(cohort)
    original_mode = app.selected_mode
    await select_rows(app, pilot, rows[:1], base)
    assert await pilot.click(rows[2], shift=True)
    (base / 'initial-selection-state.json').write_text(json.dumps({
        'sidebar_state': FieldCodec.encode(app.sidebar_state),
        'cohort': cohort,
        'expected_targets': ordered_cohort,
        'row_visibility': {row.target_name: row in app.screen._compositor.visible_widgets for row in rows},
    }, indent=2))
    assert tuple(item.target for item in app.sidebar_state.selected_targets) == ordered_cohort
    assert app.selected_mode == original_mode
    assert await pilot.click(rows[1], control=True)
    assert tuple(item.target for item in app.sidebar_state.selected_targets) == tuple(
        name for name in ordered_cohort if name != 'batch-b')
    checks.append('native-control-toggle-shift-range-without-opening-thread')

    viewer = comms.messaging.user_identity(str(project)).name
    comms.messaging.send('batch-a', 'batch-b', 'Private executor-only batch receipt')
    comms.messaging.send('batch-a', viewer, 'Private human batch receipt')
    comms.messaging.send('batch-a', '#batch', 'Private channel batch receipt')
    executor_before = (comms.bus.pending_count('batch-b', 'batch-a'),
                       comms.bus.pending_count('batch-b', '#batch'))
    assert all(executor_before)
    channel = sidebar.projection.channels['#batch']
    await select_rows(app, pilot, (rows[0], channel), base)
    selected = app.sidebar_state.selected_targets
    await choose(app, pilot, rows[0], 'read-target', {'worktree': str(project)}, base)
    assert app.sidebar_state.selected_targets == selected
    human = comms.views.viewer_snapshot(str(project))
    assert human.thread_unread['batch-a'] == human.unread.get('batch-a', 0) == 0
    assert human.channel_unread['#batch'] == 0
    assert (comms.bus.pending_count('batch-b', 'batch-a'),
            comms.bus.pending_count('batch-b', '#batch')) == executor_before
    checks.append('mixed-thread-channel-human-read-leaves-executor-delivery-pending')

    await select_rows(app, pilot, (rows[0], rows[1], channel), base)
    await choose(app, pilot, rows[0], 'pin-thread', {}, base)
    catalog = comms.channels.catalog.read()
    assert catalog.resolve('#batch').pinned
    assert catalog.pinned_threads('#batch') == {'batch-a', 'batch-b'}
    checks.append('mixed-channel-and-thread-pins-through-original-row-context')

    # Change availability through the real command between menu and execution.
    # No fabricated active status or replaced command implementation is used.
    await select_rows(app, pilot, rows[:2], base)
    menu = await open_menu(app, pilot, rows[0])
    await command(comms.root, 'archive', '--name', 'batch-b')
    app.clear_notifications()
    assert await pilot.click(menu['archive'])
    await until(pilot, lambda: not app.thread_actions.pending)
    snapshot = comms.registry.snapshot()
    assert isinstance(snapshot.status('batch-a'), ArchivedThreadStatus)
    assert isinstance(snapshot.status('batch-b'), ArchivedThreadStatus)
    assert isinstance(snapshot.status('batch-c'), StoppedThreadStatus)
    notifications = tuple(app._notifications)
    assert len(notifications) == 1 and notifications[0].severity == 'error'
    assert '1/2 completed' in notifications[0].message and 'batch-b' in notifications[0].message
    checks.append('acquired-batch-menu-rebinds-and-reports-real-partial-failure')

    for name, tags in (('exclusive-inactive', {'remove-only'}),
                       ('multiple-inactive', {'remove-only', 'keep-other'})):
        comms.registry.declare(Thread(name, frozenset(tags), str(project)), StoppedThreadStatus())
    comms.threads.restore_stopped(comms.registry.snapshot(), ('exclusive-inactive', 'multiple-inactive'))
    survivor = comms.registry.require('multiple-inactive')
    sidebar = await wait_channel_roster(app, pilot, '#remove-only')
    await select_rows(app, pilot, (sidebar.projection.channels['#remove-only'],), base)
    await choose(app, pilot, sidebar.projection.channels['#remove-only'], 'delete-tag',
        {'disposition': DeleteExclusiveInactiveThreadsTagDisposition.declared_name}, base)
    assert 'exclusive-inactive' not in comms.registry
    retained = comms.registry.require('multiple-inactive')
    assert retained.incarnation == survivor.incarnation and retained.tags == {'keep-other'}
    assert retained.session_file == survivor.session_file and retained.process_identity == survivor.process_identity
    await until(pilot, lambda: '#remove-only' not in sidebar.projection.channels)
    checks.append('native-editor-exclusive-inactive-delete-retains-multitag-incarnation')
    # A clipped row remains part of the original admitted hierarchy. Exercise
    # the production range through native pointer input in this SAME App.
    range_names = tuple(f'range-{index:02}' for index in range(60))
    for name in range_names:
        comms.registry.declare(Thread(name, frozenset({'range'}), str(project)), StoppedThreadStatus())
    comms.threads.restore_stopped(comms.registry.snapshot(), range_names)
    anchor = await reveal_thread_row(app, pilot, range_names[0], '#range')
    await select_rows(app, pilot, (anchor,), base)
    endpoint = await reveal_thread_row(app, pilot, range_names[-1], '#range')
    assert anchor not in app.screen._compositor.visible_widgets and endpoint in app.screen._compositor.visible_widgets
    ordered_range = tuple(row.target_name for row in sidebar.projection.rows
                          if sidebar.navigation.selection_for(row).channel == '#range'
                          and row.target_name in range_names)
    assert len(ordered_range) == len(range_names) and set(ordered_range) == set(range_names)
    assert await pilot.click(endpoint, shift=True)
    (base / 'scrolled-range-selection-state.json').write_text(json.dumps({
        'sidebar_state': FieldCodec.encode(app.sidebar_state),
        'expected_targets': ordered_range,
        'anchor_visible': anchor in app.screen._compositor.visible_widgets,
        'endpoint_visible': endpoint in app.screen._compositor.visible_widgets,
    }, indent=2))
    assert tuple(item.target for item in app.sidebar_state.selected_targets) == ordered_range
    assert app.selected_mode == original_mode
    checks.append('native-shift-range-retains-offscreen-anchor-across60-admitted-rows')
    assert app._exception is None


async def started_target_connections(base, *, batch=False, selection_checks=True):
    """Use the original SDK/ACP fixture, with no native prompt or model call."""
    from l0a_native_installed_pilot import main as native_journey
    from toad.acp.agent_session import AgentSession
    from toad.conversation_kind import DmConversation
    from functools import partial

    evidence = base / 'start-connections'
    evidence.mkdir()
    os.environ['L0A_EVIDENCE'] = str(evidence)
    os.environ['TMPDIR'] = str(base)
    calls = []
    frames = set()
    code = AgentSession.reconnect.__code__

    def observe(frame, event, _argument):
        if event == 'call' and frame.f_code is code and frame not in frames:
            # Coroutine resumes report another call event for the same frame.
            # Keep each actual invocation once, without replacing the method.
            frames.add(frame)
            calls.append(frame.f_locals['self'].agent)

    async def acceptance(app, pilot, actor, comms, _entered, _release, _hold, requests):
        from agent_comms.cli_commands import StartCliCommand
        actor_mode = app.selected_mode
        actor_source = app.selected_session
        project = actor_source.project_path
        original = comms.registry.require('beta')
        comms.registry.declare(Thread('peer', frozenset({'team'}), str(project),
            model=original.model, thinking_level=original.thinking_level), StoppedThreadStatus())
        comms.threads.restore_stopped(comms.registry.snapshot(), ('peer',))
        # A retained alias must select the same original native B admission.
        actor_process = actor.process.process
        actor_session = actor.session
        actor_contents = actor_source.conversation.contents
        inputs = comms.root / 'input_dispositions.json'
        before_inputs = inputs.read_bytes() if inputs.exists() else None

        async def start_from_dm():
            await app.session_navigation.history(owner_mode=actor_mode, project_path=project,
                me='beta', target='peer', kind=DmConversation)
            chat = app.selected_session.query_one(CommsChatView)
            context = await chat.command_target_context()
            definition = next(item for item in await app.preparation.run_thread(context.available_actions)
                              if item.declaration is StartCliCommand)
            from toad.thread_actions import ThreadAction
            ThreadAction.collect(context, definition)
            await app.thread_actions.close()

        if batch:
            await batch_started_target_actions(app, pilot, actor, comms, project, evidence, requests, calls, observe,
                                              selection_checks=selection_checks)
            return

        threading.setprofile_all_threads(observe)
        try:
            await start_from_dm()
            assert comms.registry.require('peer').process_alive
            assert calls == [], 'No B source is open; A must not reconnect'
            await app.preparation.run_thread(partial(comms.threads.rename_managed_thread,
                'peer', 'peer-current', owner_pid=comms.registry.require('peer').pid))
            peer_mode = await app.thread_navigation.open(owner_mode=actor_mode,
                project_path=project, target='peer')
            peer_source = app.session_navigation.source(peer_mode)
            await until(pilot, lambda: peer_source.conversation.agent is not None)
            peer = peer_source.conversation.agent
            await until(pilot, peer.session.settled.is_set,
                        failure_prefix=evidence / 'peer-startup-failure', native_wait=True)
            assert peer.session.connected
            await peer.stop()
            await app.preparation.run_thread(comms.owners.stop, 'peer')
            await start_from_dm()
            assert calls == [peer], 'Only the already-bound original B source may reconnect'
            assert peer.session.connected and comms.registry.require('peer').process_alive
            assert actor.process.process is actor_process and actor_process.returncode is None
            assert actor.session is actor_session and actor.session.connected
            assert actor_source.conversation.contents is actor_contents
            assert app.session_navigation.source(actor_mode) is actor_source
            # Sidebar actions have no captured view mode. They still refresh
            # the original already-open native B resource after a fresh start.
            await peer.stop()
            await app.preparation.run_thread(comms.owners.stop, 'peer')
            from toad.target_commands import TargetContext
            from toad.thread_actions import ThreadAction
            context = TargetContext(app, comms, 'peer', 'beta', project)
            definition = next(item for item in await app.preparation.run_thread(context.available_actions)
                              if item.declaration is StartCliCommand)
            ThreadAction.collect(context, definition)
            await app.thread_actions.close()
            assert calls == [peer, peer] and peer.session.connected
            assert actor.process.process is actor_process and actor_process.returncode is None
            assert actor_source.conversation.contents is actor_contents
            assert (inputs.read_bytes() if inputs.exists() else None) == before_inputs
            assert requests == []
            (evidence / 'receipt.json').write_text(json.dumps({
                'result': 'PASS', 'actor': 'beta', 'peer': 'peer-current',
                'actor_connection_and_reader_unchanged': True,
                'no_open_peer_reconnections': 0, 'dm_bound_peer_reconnections': 1,
                'sidebar_bound_peer_reconnections': 1,
                'alias_preserved': True, 'provider_calls': 0, 'native_inputs': 0}, indent=2)+'\n')
        finally:
            threading.setprofile_all_threads(None)

    await native_journey(acceptance=acceptance, provider_request_budget=0,
                         fixture_stage=base / 'start-fixture', app_type=ToadApp)
    if batch:
        receipt = json.loads((evidence / 'receipt.json').read_text())
        receipt.update(result='PASS', whole_app_shutdown_completed=True,
                       original_sdk_fixture_cleanup_completed=True)
        (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')



async def batch_started_target_actions(app, pilot, actor, comms, project, evidence, requests, reconnects, observe_reconnect,
                                      *, selection_checks=True):
    """Existing selection checks and native batches share one SDK/ACP App."""
    from agent_comms.owner_lifecycle import OwnerLifecycle

    original_actor = actor.process.process
    actor_session = actor.session
    actor_source = app.selected_session
    actor_contents = actor_source.conversation.contents
    actor_mode = app.selected_mode
    original = comms.registry.require('beta')
    comms.channels.update_tags('peer', add=frozenset({'batch-native'}))
    comms.channels.update_tags('peer', remove=frozenset({'team'}))
    comms.registry.declare(Thread('peer-two', frozenset({'batch-native'}), str(project),
        model=original.model, thinking_level=original.thinking_level), StoppedThreadStatus())
    comms.threads.restore_stopped(comms.registry.snapshot(), ('peer-two',))
    app.settings.sidebar.show_stopped = True
    calls = {'start': [], 'stop': []}
    codes = {OwnerLifecycle.start.__code__: calls['start'], OwnerLifecycle.stop.__code__: calls['stop']}
    catalog_code = CliCommand.target_catalog.__func__.__code__
    catalog_reads = []
    ui_thread = threading.get_ident()
    def observed(frame, event, argument):
        observe_reconnect(frame, event, argument)
        if event == 'call' and frame.f_code in codes:
            codes[frame.f_code].append(frame.f_locals['name'])
        if event == 'call' and frame.f_code is catalog_code:
            catalog_reads.append({'thread': threading.get_ident(), 'target': frame.f_locals['target']})

    async def selected(operation):
        sidebar = await wait_channel_roster(app, pilot, '#batch-native')
        row = await reveal_thread_row(app, pilot, 'peer', '#batch-native')
        channel = sidebar.projection.channels['#batch-native']
        await select_rows(app, pilot, (channel, row), evidence)
        await choose(app, pilot, channel, operation, {}, evidence)

    identities = []
    inputs = comms.root / 'input_dispositions.json'
    before_inputs = inputs.read_bytes() if inputs.exists() else None
    threading.setprofile_all_threads(observed)
    try:
        checks = []
        if selection_checks:
            await selected_target_actions(app, pilot, comms, project, evidence, checks)
        await selected('start')
        assert calls['start'] == ['peer', 'peer-two']
        assert reconnects == []
        assert all(comms.registry.require(name).process_alive for name in ('peer', 'peer-two'))
        identities.extend(comms.registry.require(name).require_process() for name in ('peer', 'peer-two'))
        mode = await app.thread_navigation.open(owner_mode=actor_mode, project_path=project, target='peer')
        source = app.session_navigation.source(mode)
        await until(pilot, lambda: source.conversation.agent is not None)
        peer = source.conversation.agent
        await until(pilot, peer.session.settled.is_set,
                        failure_prefix=evidence / 'peer-startup-failure', native_wait=True)
        assert peer.session.connected
        # Retire this fixture's original ACP connection before stopping its
        # native owners, exactly as the existing single-start control does.
        await peer.stop()
        await selected('stop')
        assert calls['stop'] == ['peer', 'peer-two']
        assert all(comms.registry.status(name).stopped and not comms.registry.require(name).process_alive
                   for name in ('peer', 'peer-two'))
        assert all(not Path('/proc', str(identity.pid)).exists() for identity in identities)
        await selected('start')
        assert calls['start'] == ['peer', 'peer-two', 'peer', 'peer-two']
        assert reconnects == [peer] and peer.session.connected
        assert app.session_navigation.source(mode) is source
        identities.extend(comms.registry.require(name).require_process() for name in ('peer', 'peer-two'))
        assert actor.process.process is original_actor and original_actor.returncode is None
        assert actor.session is actor_session and actor.session.connected
        assert actor_source.conversation.contents is actor_contents
        assert requests == []

        # Real active original owners must survive the granular tag operation.
        for name in ('peer', 'peer-two'):
            comms.channels.update_tags(name, add=frozenset({'remove-native'}))
        comms.registry.declare(Thread('remove-stopped', frozenset({'remove-native'}), str(project)), StoppedThreadStatus())
        comms.threads.restore_stopped(comms.registry.snapshot(), ('remove-stopped',))
        before = {name: comms.registry.require(name) for name in ('peer', 'peer-two')}
        sidebar = await wait_channel_roster(app, pilot, '#remove-native')
        channel = sidebar.projection.channels['#remove-native']
        await select_rows(app, pilot, (channel,), evidence)
        await choose(app, pilot, channel, 'delete-tag',
            {'disposition': DeleteExclusiveInactiveThreadsTagDisposition.declared_name}, evidence)
        assert 'remove-stopped' not in comms.registry
        for name, captured in before.items():
            retained = comms.registry.require(name)
            assert retained.incarnation == captured.incarnation
            assert retained.process_identity == captured.process_identity and retained.process_alive
            assert retained.tags == {'batch-native'} and retained.session_file == captured.session_file
        await until(pilot, lambda: '#remove-native' not in sidebar.projection.channels)
        await peer.stop()
        await selected('stop')
        assert calls['stop'] == ['peer', 'peer-two', 'peer', 'peer-two']
        assert all(not Path('/proc', str(identity.pid)).exists() for identity in identities)
        assert (inputs.read_bytes() if inputs.exists() else None) == before_inputs
        assert requests == [] and app._exception is None
        assert catalog_reads and all(read['thread'] != ui_thread for read in catalog_reads)
        checks.append('all-observed-selection-catalog-reads-off-ui-loop')
        (evidence / 'receipt.json').write_text(json.dumps({
            'result': 'ASSERTIONS_PASS_SHUTDOWN_PENDING',
            'native_owner_start_calls': calls['start'], 'native_owner_stop_calls': calls['stop'],
            'overlapping_channel_thread_deduplicated': True,
            'only_original_open_peer_reconnected': len(reconnects),
            'actor_connection_and_reader_unchanged': True,
            'active_tag_survivors_preserved': True,
            'selected_target_checks': checks,
            'catalog_reads': catalog_reads,
            'ui_thread': ui_thread,
            'provider_calls': 0, 'native_inputs': 0,
            'original_process_identities': [FieldCodec.encode(identity) for identity in identities],
        }, indent=2) + '\n')
    finally:
        threading.setprofile_all_threads(None)


async def deleted_native_connections(base):
    """Delete a stopped B with a hidden native view and selected A-to-B history."""
    from l0a_native_installed_pilot import main as native_journey
    from toad.conversation_kind import DmConversation
    evidence = base / 'native-view-delete'
    evidence.mkdir()
    os.environ.update(L0A_EVIDENCE=str(evidence), TMPDIR=str(base))

    async def acceptance(app, pilot, actor, comms, _entered, _release, _hold, requests):
        actor_mode = app.selected_mode
        actor_source = app.selected_session
        project = actor_source.project_path
        original = comms.registry.require('beta')
        comms.registry.declare(Thread('peer', frozenset({'native-delete'}), str(project),
            model=original.model, thinking_level=original.thinking_level), StoppedThreadStatus())
        comms.threads.restore_stopped(comms.registry.snapshot(), ('peer',))
        await app.preparation.run_thread(comms.owners.start, 'peer')
        native_mode = await app.thread_navigation.open(owner_mode=actor_mode,
            project_path=project, target='peer')
        native_source = app.session_navigation.source(native_mode)
        await until(pilot, lambda: native_source.conversation.agent is not None)
        peer = native_source.conversation.agent
        await until(pilot, peer.session.settled.is_set,
                        failure_prefix=evidence / 'peer-startup-failure', native_wait=True)
        assert peer.session.connected
        history_mode = await app.session_navigation.history(owner_mode=actor_mode,
            project_path=project, me='beta', target='peer', kind=DmConversation)
        assert app.selected_mode == history_mode
        assert native_mode in app.workspace_sessions.views
        actor_process = actor.process.process
        actor_contents = actor_source.conversation.contents
        inputs = comms.root / 'input_dispositions.json'
        before_inputs = inputs.read_bytes() if inputs.exists() else None
        await peer.stop()
        await app.preparation.run_thread(comms.owners.stop, 'peer')
        result = await command(comms.root, 'delete-tag', '--name', 'native-delete',
            '--disposition', FieldCodec.encode(DeleteThreadsTagDisposition), '--confirmed')
        assert [item['name'] for item in result['removed_threads']] == ['peer']
        await until(pilot, lambda: all(mode not in app.workspace_sessions.views
            and app.session_navigation.get(mode) is None for mode in (native_mode, history_mode)))
        assert not native_source.is_attached
        assert actor.process.process is actor_process and actor_process.returncode is None
        assert actor_source.conversation.contents is actor_contents and actor.session.connected
        assert (inputs.read_bytes() if inputs.exists() else None) == before_inputs
        assert requests == []
        (evidence / 'receipt.json').write_text(json.dumps({
            'result': 'ASSERTIONS_PASS_SHUTDOWN_PENDING',
            'closed_current_history_and_hidden_native': True,
            'actor_connection_and_reader_unchanged': True, 'input_bytes_unchanged': True,
            'provider_calls': 0, 'native_inputs': 0}, indent=2)+'\n')

    await native_journey(acceptance=acceptance, provider_request_budget=0,
                         fixture_stage=base / 'delete-fixture', app_type=ToadApp)
    # The callback precedes run_test.__aexit__ and the original SDK fixture's
    # finally block. Qualify the whole case only after both owners have joined.
    receipt = json.loads((evidence / 'receipt.json').read_text())
    receipt.update(result='PASS', whole_app_shutdown_completed=True,
                   original_sdk_fixture_cleanup_completed=True)
    (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')


async def journey(args):
    start = time.monotonic()
    base = args.output.resolve()
    base.mkdir(parents=True, exist_ok=False)
    project = base / 'project'
    project.mkdir()
    os.environ.update(XDG_CONFIG_HOME=str(base / 'config'), XDG_STATE_HOME=str(base / 'state'),
                      XDG_DATA_HOME=str(base / 'data'), AGENT_COMMS_ROOT=str(base / 'wire'))
    os.environ.pop('NO_COLOR', None)
    os.environ.pop('PYTHONPATH', None)
    comms = private_native_wire(base / 'wire')
    from toad.widgets.comms_chat import session_thread_name
    names = ('viewer', 'tagged', session_thread_name(project))
    for name in names:
        comms.registry.declare(Thread(name, frozenset({'first'}), str(project)), StoppedThreadStatus())
    comms.threads.restore_stopped(comms.registry.snapshot(), names)
    original = comms.registry.require('tagged').incarnation
    comms.channels.set_saved_view(SavedView('projection', ViewKind.PARTICIPANTS,
                                           ViewPredicate(AnyOfMatch, frozenset({'first'}))))
    before = {'root_id': os.environ['AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID'],
              'incarnation': FieldCodec.encode(original), 'inputs': 0}
    checks = []
    # Observe the original installed implementation without replacing queries,
    # application state or protocol. This catches a catalog consumer returning
    # to synchronous UI-loop I/O in the same affected workflow.
    ui_thread = threading.get_ident()
    catalog_reads = []
    code = CliCommand.target_catalog.__func__.__code__
    def observe(frame, event, _argument):
        if event == 'call' and frame.f_code is code:
            catalog_reads.append({'thread': threading.get_ident(),
                                  'target': frame.f_locals['target']})
    threading.setprofile_all_threads(observe)
    app = ToadApp(project_dir=str(project))
    async with app.run_test(size=(125, 48), headless=not args.physical) as pilot:
        if args.selected_only:
            await selected_target_actions(app, pilot, comms, project, base, checks)
        else:
            owner = app.session_navigation.get(app.selected_mode)
            sidebar = await wait_channel_roster(app, pilot, '#first', '#all')
            await mounted_layers(app, pilot)
            checks.append('corrected-mounted-layer-owner-custom-duplicates-empty-restoration')
            row = await reveal_thread_row(app, pilot, 'tagged', '#first')
            await choose(app, pilot, row, 'thread-tags', {'tags': 'first,second'}, base)
            assert comms.registry.require('tagged').tags == frozenset({'first','second'})
            checks.append('native-right-click-thread-tags-original-membership')
            await until(pilot, lambda: '#second' in sidebar.projection.channels)
            channel = sidebar.projection.channels['#second']
            await choose(app, pilot, channel, 'rename-tag', {'new_name': 'renamed'}, base)
            assert comms.registry.require('tagged').tags == frozenset({'first','renamed'})
            await until(pilot, lambda: '#renamed' in sidebar.projection.channels and '#second' not in sidebar.projection.channels)
            checks.append('native-right-click-rename-observed-current-sidebar')
            app.save_screenshot(str(base / 'renamed-sidebar.svg'))
            builtin = sidebar.projection.channels['#all']
            menu = await open_menu(app, pilot, builtin)
            assert not {'rename-tag','delete-tag','delete-view'} & menu.keys()
            await pilot.press('escape')
            checks.append('builtin-applicability-owned-by-backend')
            channel = sidebar.projection.channels['#renamed']
            await choose(app, pilot, channel, 'delete-tag', {}, base)
            assert comms.registry.require('tagged').tags == frozenset({'first'})
            await until(pilot, lambda: '#renamed' not in sidebar.projection.channels)
            checks.append('native-reviewable-delete-original-tags-updated')
            view = sidebar.projection.channels['#projection']
            await choose(app, pilot, view, 'delete-view', {}, base)
            assert 'projection' not in comms.channels.catalog.read().saved_views
            checks.append('native-saved-view-delete-original-catalog')
            chat = await open_channel(app, pilot, '#first')
            await until(pilot, lambda: any(item.command == '/pin-channel'
                                          for item in chat.prompt.slash_commands))
            before_reads = len(catalog_reads)
            catalog = await chat.read_command_catalog()
            assert len(catalog_reads) == before_reads + 1
            assert any(item.command == '/pin-channel' for item in catalog.commands)
            # Both existing native consumers execute a freshly acquired projection;
            # the actual prompt/Enter drives the channel submission consumer here.
            await slash(chat, pilot, '/pin-channel')
            await until(pilot, lambda: comms.channels.catalog.read().resolve('#first').pinned)
            await until(pilot, lambda: not app.thread_actions.pending)
            checks.append('slash-single-acquisition-refresh-and-native-enter-execution')
            # CLI uses the same original typed operation; already-mounted UI derives
            # the new canonical revision without a local tag/status assignment.
            response = await command(comms.root, 'thread-tags', '--name', 'tagged', '--tags', 'first,cli-tag')
            assert response['tags'] == ['cli-tag','first']
            await until(pilot, lambda: '#cli-tag' in sidebar.projection.channels)
            checks.append('same-private-bus-cli-change-visible-in-open-native-app')
            original_view = app.selected_session
            await open_channel(app, pilot, '#all')
            await command(comms.root, 'thread-tags', '--name', 'tagged', '--tags', 'first,cli-tag,hidden-tag')
            sidebar = await wait_channel_roster(app, pilot, '#hidden-tag')
            label = next(label for label in app.screen.query(SessionLabel)
                         if label.id == original_view.id)
            label.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert await pilot.click(label)
            await until(pilot, lambda: app.selected_session is original_view)
            returned = original_view.query_one(CommsChatView)
            assert returned is chat
            await until(pilot, lambda: any(item.command == '/pin-channel'
                                          for item in returned.prompt.slash_commands))
            await slash(returned, pilot, '/pin-channel')
            await until(pilot, lambda: not comms.channels.catalog.read().resolve('#first').pinned)
            await until(pilot, lambda: not app.thread_actions.pending)
            app.save_screenshot(str(base / 'slash-hidden-return.svg'))
            checks.append('hidden-backend-change-original-tab-return-fresh-slash-execution')
            assert comms.registry.require('tagged').incarnation == original
            # Channel visibility is a reversible catalog preference, independently
            # of the three tagged-thread outcomes. Hidden admitted channels close
            # through the same original workspace resource as selected channels.
            channel_modes = tuple(entry.mode for entry in app.session_navigation.members
                                  if entry.original_channels() == ((str(comms.root), '#first'),))
            original_registry = comms.registry.snapshot()
            await command(comms.root, 'archive-channel', '--name', '#first')
            await until(pilot, lambda: all(app.session_navigation.get(mode) is None for mode in channel_modes))
            assert comms.registry.snapshot() == original_registry
            assert comms.channels.catalog.read().resolve('#first').archived
            await command(comms.root, 'restore-channel', '--name', '#first')
            await wait_channel_roster(app, pilot, '#first')
            assert not comms.channels.catalog.read().resolve('#first').archived
            assert comms.registry.snapshot() == original_registry
            checks.append('archive-restore-channel-only-preference-no-thread-tag-history-mutation')

            for name, tag in (('archive-a', 'archive-cohort'), ('delete-a', 'delete-cohort'),
                              ('delete-b', 'delete-cohort')):
                comms.registry.declare(Thread(name, frozenset({tag}), str(project)), StoppedThreadStatus())
            comms.threads.restore_stopped(comms.registry.snapshot(), ('archive-a', 'delete-a', 'delete-b'))
            await wait_channel_roster(app, pilot, '#archive-cohort', '#delete-cohort')
            sidebar = await wait_channel_roster(app, pilot, '#archive-cohort')
            await choose(app, pilot, sidebar.projection.channels['#archive-cohort'], 'delete-tag',
                         {'disposition': ArchiveThreadsTagDisposition.declared_name}, base)
            assert comms.registry.status('archive-a').declared_name == 'archived'
            assert comms.registry.require('archive-a').tags == {'archive-cohort'}
            assert '#archive-cohort' in comms.channels.channels()
            checks.append('native-form-archive-tagged-threads-preserves-tag-channel-and-history')

            from toad.conversation_kind import DmConversation
            removed_modes = []
            for peer in ('delete-a', 'delete-b'):
                removed_modes.append(await app.session_navigation.history(
                    owner_mode=owner.mode, project_path=project, me='viewer', target=peer, kind=DmConversation))
            assert app.selected_mode == removed_modes[-1]
            assert all(mode in app.workspace_sessions.views for mode in removed_modes)
            inputs = comms.root / 'input_dispositions.json'
            input_bytes = inputs.read_bytes() if inputs.exists() else None
            response = await command(comms.root, 'delete-tag', '--name', 'delete-cohort',
                                     '--disposition', DeleteThreadsTagDisposition.declared_name, '--confirmed')
            assert {row['name'] for row in response['removed_threads']} == {'delete-a', 'delete-b'}
            await until(pilot, lambda: all(mode not in app.workspace_sessions.views
                                          and app.session_navigation.get(mode) is None for mode in removed_modes))
            assert all(peer not in comms.registry for peer in ('delete-a', 'delete-b'))
            assert (inputs.read_bytes() if inputs.exists() else None) == input_bytes
            reopened_mode = await app.session_navigation.history(owner_mode=owner.mode,
                project_path=project, me='viewer', target='delete-a', kind=DmConversation)
            assert reopened_mode not in removed_modes
            assert all(app.session_navigation.get(mode) is None for mode in removed_modes)
            checks.append('cli-delete-actual-backend-cohort-closes-current-hidden-views-refuses-reopen')
            assert app._exception is None
    if not args.selected_only:
        reopened = ToadApp(project_dir=str(project))
        async with reopened.run_test(size=(125,48), headless=not args.physical) as pilot:
            sidebar = await wait_channel_roster(reopened, pilot, '#first', '#cli-tag', '#hidden-tag')
            row = await reveal_thread_row(reopened, pilot, 'tagged', '#cli-tag')
            menu = await open_menu(reopened, pilot, row)
            assert await pilot.click(menu['thread-tags'])
            await until(pilot, lambda: isinstance(reopened.screen, CommandDialog)
                        and reopened.screen.is_mounted)
            assert reopened.screen.query_one('#command-field-tags', Input).value == 'cli-tag, first, hidden-tag'
            reopened.save_screenshot(str(base / 'saved-reopen-tags.svg'))
            await pilot.press('escape')
            assert reopened._exception is None
        checks.append('save-reopen-original-registry-tags-no-frontend-copy')
    assert catalog_reads and all(read['thread'] != ui_thread for read in catalog_reads)
    checks.append('all-observed-catalog-reads-off-ui-loop')
    threading.setprofile_all_threads(None)
    await asyncio.get_running_loop().shutdown_default_executor()
    receipt = {'result':'PASS','scope':'installed App native widget + same-root CLI; no provider/native input/public writes',
               'physical_linux_driver':args.physical,'seconds':time.monotonic()-start,'checks':checks,
               'before':before,'after':{'incarnation':FieldCodec.encode(comms.registry.require('tagged').incarnation),
                                     'tags':sorted(comms.registry.require('tagged').tags)},
               'catalog_reads':catalog_reads,'ui_thread':ui_thread,
               'source':{'toad':str(Path(__import__('toad').__file__).resolve()),
                         'core':str(Path(__import__('agent_comms').__file__).resolve()),
                         'python':sys.executable},'provider_calls':0,'native_inputs':0}
    (base / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--physical',action='store_true')
    parser.add_argument('--selected-only', action='store_true', help='Affected selected-target menus and private-store outcomes; no old ordinary journey replay')
    parser.add_argument('--batch-native-only', action='store_true', help='Selected channel/member start-stop deduplication and original ACP reconnect; zero provider prompts')
    parser.add_argument('--batch-start-stop-only', action='store_true', help='Remaining native start/stop/reconnect and active tag preservation; omit previously accepted selection checks')
    parser.add_argument('--start-only', action='store_true', help='Original SDK/ACP Start-target resource control')
    parser.add_argument('--delete-native-only', action='store_true', help='Current history and hidden native view retirement')
    args = parser.parse_args()
    if args.batch_native_only or args.batch_start_stop_only:
        args.output.mkdir(parents=True, exist_ok=False)
        asyncio.run(started_target_connections(args.output.resolve(), batch=True,
                                             selection_checks=not args.batch_start_stop_only))
    elif args.start_only:
        args.output.mkdir(parents=True, exist_ok=False)
        asyncio.run(started_target_connections(args.output.resolve()))
    elif args.delete_native_only:
        args.output.mkdir(parents=True, exist_ok=False)
        asyncio.run(deleted_native_connections(args.output.resolve()))
    else:
        asyncio.run(journey(args))
