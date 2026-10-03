"""One installed App/menu and CLI journey on the same owned private bus.

No provider, public bus or native input. Imports product code from its installed
wheel; the existing pilot controls native widgets and the original backend CLI.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

from agent_comms.channels import SavedView, ViewKind, ViewPredicate, AnyOfMatch
from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
from agent_comms.thread_status import StoppedThreadStatus
from agent_comms.threads import Thread
from textual.widgets import Input, TextArea
from toad.app import ToadApp
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar
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
        assert await pilot.click(editor)
        if isinstance(editor, TextArea):
            editor.text = value
        else:
            assert isinstance(editor, Input)
            editor.value = value
    app.save_screenshot(str(evidence / (operation + '-review.svg')))
    assert await pilot.click('#command-apply')
    await until(pilot, lambda: not isinstance(app.screen, CommandDialog) and not app.thread_actions.pending)


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
    before = {'root_id': comms.bus.log.read_metadata().root_id,
              'incarnation': FieldCodec.encode(original), 'inputs': 0}
    checks = []
    app = ToadApp(project_dir=str(project))
    async with app.run_test(size=(125, 48), headless=not args.physical) as pilot:
        sidebar = await wait_channel_roster(app, pilot, ('#first', '#all'))
        row = await reveal_thread_row(app, pilot, 'tagged', '#first')
        await choose(app, pilot, row, 'thread-tags', {'tags': 'first,second'}, base)
        assert comms.registry.require('tagged').tags == frozenset({'first','second'})
        checks.append('native-right-click-thread-tags-original-membership')
        await until(pilot, lambda: '#second' in sidebar.projection.channels)
        channel = sidebar.projection.channels['#second'].row
        await choose(app, pilot, channel, 'rename-tag', {'new_name': 'renamed'}, base)
        assert comms.registry.require('tagged').tags == frozenset({'first','renamed'})
        await until(pilot, lambda: '#renamed' in sidebar.projection.channels and '#second' not in sidebar.projection.channels)
        checks.append('native-right-click-rename-observed-current-sidebar')
        app.save_screenshot(str(base / 'renamed-sidebar.svg'))
        builtin = sidebar.projection.channels['#all'].row
        menu = await open_menu(app, pilot, builtin)
        assert not {'rename-tag','delete-tag','delete-view'} & menu.keys()
        await pilot.press('escape')
        checks.append('builtin-applicability-owned-by-backend')
        channel = sidebar.projection.channels['#renamed'].row
        await choose(app, pilot, channel, 'delete-tag', {}, base)
        assert comms.registry.require('tagged').tags == frozenset({'first'})
        await until(pilot, lambda: '#renamed' not in sidebar.projection.channels)
        checks.append('native-reviewable-delete-original-tags-updated')
        view = sidebar.projection.channels['#projection'].row
        await choose(app, pilot, view, 'delete-view', {}, base)
        assert 'projection' not in comms.channels.catalog.read().saved_views
        checks.append('native-saved-view-delete-original-catalog')
        # CLI uses the same original typed operation; already-mounted UI derives
        # the new canonical revision without a local tag/status assignment.
        response = await command(comms.root, 'thread-tags', '--name', 'tagged', '--tags', 'first,cli-tag')
        assert response['tags'] == ['cli-tag','first']
        await until(pilot, lambda: '#cli-tag' in sidebar.projection.channels)
        checks.append('same-private-bus-cli-change-visible-in-open-native-app')
        assert comms.registry.require('tagged').incarnation == original
        assert app._exception is None
    reopened = ToadApp(project_dir=str(project))
    async with reopened.run_test(size=(125,48), headless=not args.physical) as pilot:
        sidebar = await wait_channel_roster(reopened, pilot, ('#first','#cli-tag'))
        row = await reveal_thread_row(reopened, pilot, 'tagged', '#cli-tag')
        menu = await open_menu(reopened, pilot, row)
        assert await pilot.click(menu['thread-tags'])
        await until(pilot, lambda: isinstance(reopened.screen, CommandDialog))
        assert reopened.screen.query_one('#command-field-tags', Input).value == 'cli-tag, first'
        reopened.save_screenshot(str(base / 'saved-reopen-tags.svg'))
        await pilot.press('escape')
        assert reopened._exception is None
    checks.append('save-reopen-original-registry-tags-no-frontend-copy')
    await asyncio.get_running_loop().shutdown_default_executor()
    receipt = {'result':'PASS','scope':'installed App native widget + same-root CLI; no provider/native input/public writes',
               'physical_linux_driver':args.physical,'seconds':time.monotonic()-start,'checks':checks,
               'before':before,'after':{'incarnation':FieldCodec.encode(comms.registry.require('tagged').incarnation),
                                     'tags':sorted(comms.registry.require('tagged').tags)},
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
