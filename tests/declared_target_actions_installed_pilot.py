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
from agent_comms.channel_management import ArchiveThreadsTagDisposition, DeleteThreadsTagDisposition
from agent_comms.field_codec import FieldCodec
from agent_comms.thread_status import StoppedThreadStatus
from agent_comms.threads import Thread
from textual.widgets import Checkbox, Input, Select, TextArea
from toad.app import ToadApp
from toad.screens.comms import CommsScreen
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_command_dialog import CommandDialog
from runtime_fixture import private_native_wire, wait_channel_roster
from saved_state_user_journey_pilot import reveal_thread_row


async def until(pilot, predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await pilot.pause(.025)


async def command(root, *arguments):
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'agent_comms.cli', '--root', str(root), *arguments,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (arguments, stdout.decode(), stderr.decode())
    return json.loads(stdout)


async def open_menu(app, pilot, row):
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row, button=3)
    await until(pilot, lambda: isinstance(app.screen, ContextMenu))
    return {item.action: item for item in app.screen.query(ContextMenuItem)}


async def choose(app, pilot, row, operation, fields, evidence):
    menu = await open_menu(app, pilot, row)
    assert operation in menu, tuple(menu)
    assert await pilot.click(menu[operation])
    await until(pilot, lambda: isinstance(app.screen, CommandDialog))
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
    for name in ('viewer', 'tagged'):
        comms.registry.declare(Thread(name, frozenset({'first'}), str(project)), StoppedThreadStatus())
    comms.threads.restore_stopped(comms.registry.snapshot(), ('viewer', 'tagged'))
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
        sidebar = await wait_channel_roster(app, pilot, '#first', '#all')
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
        owner = app.session_navigation.get(app.selected_session.owner_mode)
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
    reopened = ToadApp(project_dir=str(project))
    async with reopened.run_test(size=(125,48), headless=not args.physical) as pilot:
        sidebar = await wait_channel_roster(reopened, pilot, '#first', '#cli-tag', '#hidden-tag')
        row = await reveal_thread_row(reopened, pilot, 'tagged', '#cli-tag')
        menu = await open_menu(reopened, pilot, row)
        assert await pilot.click(menu['thread-tags'])
        await until(pilot, lambda: isinstance(reopened.screen, CommandDialog))
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
    asyncio.run(journey(parser.parse_args()))
