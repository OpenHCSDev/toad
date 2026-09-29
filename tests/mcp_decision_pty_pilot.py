"""Installed MCP inventory -> clicked local decisions -> actual ledger -> refreshed UI.

Uses the real pinned package, NormalApp, compositor, PTY and keyboard. All
config/ledgers/wire belong to this test; no MCP server or paid provider starts.
"""

import asyncio
import faulthandler
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from textual import events
from textual.widgets import OptionList, Button, Static
from toad.app import ToadApp
from toad.mcp_commands import MCPDecision, MCPSelection, AllowCommand, ProjectTrustDecision
from toad.mcp_declarations import AllowPolicy, AskPolicy, ApprovedStatus, DeniedStatus
from toad.mcp_decision import LocalDecisionPTY
from toad.mcp_inventory import installed_mcp_command, parse_inventory, UnsupportedInventory
from toad.mcp_outcomes import StaleSnapshotOutcome
from toad.screens.mcp_decision import MCPDecisionScreen
from toad.screens.mcp_inventory import MCPInventoryScreen, MCPDecisionButton
from toad.widgets.terminal import Terminal


def viewport_text(widget):
    region = widget.region.intersection(widget.screen.region)
    return '\n'.join(strip.crop(region.x, region.right).text for strip in
                     widget.screen._compositor.render_strips()[region.y:region.bottom])


async def until(pilot, predicate):
    async with asyncio.timeout(12):
        while not predicate():
            await pilot.pause(.03)


def package_setup(package, project, agent_dir, *, trusted):
    script = r'''
import { pathToFileURL } from 'node:url';
const [packageRoot, projectRoot, agentDir, trusted, initialize] = process.argv.slice(1);
const { ProjectTrustStore } = await import(pathToFileURL(packageRoot + '/dist/index.js'));
const { writeNativeServer } = await import(pathToFileURL(packageRoot + '/agent-comms-extensions/pi-mcp-client/src/config-write.mjs'));
const trust = new ProjectTrustStore(agentDir);
if (initialize === 'true') {
  trust.set(projectRoot, true);
  for (const scope of ['user', 'project']) {
    await writeNativeServer({ agentDir, projectRoot, configDirName: '.pi', scope,
      declaration: { id: 'fixture', enabled: true, instructionsPolicy: 'status-only',
        transport: { type: 'stdio', command: 'never-launched', args: ['HIDDEN_ARGUMENT'], cwd: 'project',
          envFrom: { CHILD: 'HOST' } } }});
  }
}
trust.set(projectRoot, trusted === 'true');
'''
    subprocess.run(['node', '--input-type=module', '-e', script, str(package),
                    str(project), str(agent_dir), str(trusted).lower(),
                    str(not (project / '.pi/mcp.json').exists()).lower()], check=True, timeout=10)


def inventory_boundary(project):
    node, cli = installed_mcp_command()
    raw = subprocess.run([node, cli, 'inventory', '--json', '--project', str(project)],
                         check=True, capture_output=True, timeout=10).stdout
    snapshot = parse_inventory(raw, project)
    malformed = []
    for path, bad in (
        (('version',), True), (('projectRoot',), str(project / 'not-canonical')),
        (('live', 'state'), 'running'),
        (('declarations', 'user', 0, 'transport', 'argumentCount'), True),
        (('declarations', 'user', 0, 'transport', 'envFrom'), [['CHILD']]),
        (('declarations', 'user', 0, 'scope'), 'project'),
        (('declarations', 'user', 0, 'callPolicy'), 'allow'),
        (('declarations', 'user', 0, 'executable'), 'SECRET'),
    ):
        changed = deepcopy(json.loads(raw))
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = bad
        malformed.append(json.dumps(changed).encode())
    malformed.extend((raw.replace(b'"version":2', b'"version":2,"version":2'),
                      b'{"version":2,', b' ' * 128_001))
    for data in malformed:
        try:
            parse_inventory(data, project)
        except UnsupportedInventory:
            continue
        raise AssertionError('Invalid package inventory accepted')
    print('PASS actual-package boundary: typed fields, scope, policy, tuple lengths, unknown/duplicate fields, root and size rejection', file=sys.__stdout__, flush=True)
    return snapshot


class ApproveAgainCommand(ProjectTrustDecision):
    """A new UI case using the existing external approval operation."""
    label = 'Approve again'

    def arguments(self):
        return 'trust', 'approve'


async def main():
    package = Path(os.environ['AC_NATIVE_COPIED_PACKAGE'])
    scratch = Path(os.environ['TOAD_TEST_SCRATCH'])
    with TemporaryDirectory(prefix='mcp-journey-', dir=scratch) as directory:
        stage = Path(directory)
        project, agent_dir, root = stage / 'project', stage / 'pi', stage / 'wire'
        for path in (project, agent_dir, root):
            path.mkdir(mode=0o700)
        comms = Comms(root)
        root_id = comms.messaging.initialize_private_initial_protocol()
        os.environ.update(AGENT_COMMS_ROOT=str(root),
                          AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
                          AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
                          PI_CODING_AGENT_DIR=str(agent_dir),
                          XDG_CONFIG_HOME=str(stage / 'config'),
                          XDG_DATA_HOME=str(stage / 'data'),
                          XDG_STATE_HOME=str(stage / 'state'))
        os.environ.pop('PI_PROMPT', None)
        package_setup(package, project, agent_dir, trusted=False)
        untrusted = inventory_boundary(project)
        assert not untrusted.project_trusted_saved and not untrusted.declarations.project
        faulthandler.dump_traceback_later(100, repeat=False)
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(160, 44)) as pilot:
            print('APP_MOUNTED', file=sys.__stdout__, flush=True)
            await pilot.press('ctrl+p')
            print('PALETTE_OPEN', file=sys.__stdout__, flush=True)
            await pilot.press(*'Pi MCP inventory')
            print('PALETTE_QUERY_TYPED', file=sys.__stdout__, flush=True)
            await pilot.press('enter')
            print('PALETTE_SELECTED', file=sys.__stdout__, flush=True)
            await until(pilot, lambda: isinstance(app.screen, MCPInventoryScreen))
            screen = app.screen
            await until(pilot, lambda: screen._inventory is not None)
            print('INVENTORY_LOADED', file=sys.__stdout__, flush=True)
            listing = screen.query_one(OptionList)
            listing.focus()
            await pilot.press('down')
            await pilot.pause()
            assert all(button.disabled for button in screen.query(MCPDecisionButton))
            assert 'trust_required' in viewport_text(listing)
            assert 'HIDDEN_ARGUMENT' not in viewport_text(screen)
            print('UNTRUSTED_VISIBLE', file=sys.__stdout__, flush=True)
            package_setup(package, project, agent_dir, trusted=True)
            print('PROJECT_TRUSTED', file=sys.__stdout__, flush=True)
            assert await pilot.click('#refresh')
            await until(pilot, lambda: screen._inventory is not None and screen._inventory.project_trusted_saved)
            listing.focus()
            await pilot.press('end')
            await pilot.pause()
            print('PROJECT_ROW_SELECTED', file=sys.__stdout__, flush=True)
            assert not screen.query_one('#approve', Button).disabled
            assert screen.query_one('#allow', Button).disabled
            assert 'shadowed' in viewport_text(listing)
            assert 'Approve again' in viewport_text(screen)
            for member in MCPDecision.members_with(MCPDecision):
                command = member()
                listing.focus()
                await pilot.press('end')
                await pilot.pause()
                assert not screen.query_one(f'#{command.button_id}', Button).disabled
                row = next(row for row in screen._inventory.rows if row.scope.declared_name == 'project')
                print('BEGIN actual clicked command', command.declared_name, file=sys.__stdout__, flush=True)
                assert await pilot.click(f'#{command.button_id}')
                await until(pilot, lambda: isinstance(app.screen, MCPDecisionScreen))
                modal = app.screen
                terminal = modal.query_one(Terminal)
                await until(pilot, lambda: ' to apply:' in '\n'.join(line.content.plain for line in terminal.state.buffer.lines))
                await pilot.pause()
                assert command.arguments()[1] in viewport_text(terminal)
                assert 'never-launched' in viewport_text(terminal)
                terminal.focus()
                challenge = f'{command.arguments()[1]}:{row.id}:{row.digest}'
                app._driver.send_message(events.Paste(challenge))
                await pilot.pause()
                await pilot.press('enter')
                await until(pilot, lambda: 'CLI exited zero' in viewport_text(modal.query_one('#mcp-decision-status', Static)))
                assert modal._pty._process is None and modal._pty._master is None
                assert await pilot.click('#cancel')
                await until(pilot, lambda: app.screen is screen and screen._inventory is not None)
                changed = next(row for row in screen._inventory.rows if row.scope.declared_name == 'project')
                expected = {'approve': ApprovedStatus, 'deny': DeniedStatus}.get(command.declared_name)
                if expected is not None:
                    assert changed.status is expected, '\n'.join(line.content.plain for line in terminal.state.buffer.lines)
                print('PASS clicked installed package decision', command.declared_name, changed.status.declared_name, changed.call_policy.declared_name, file=sys.__stdout__, flush=True)
                # Family order is declaration-derived. Re-approve after deny so
                # the following call-policy decisions are valid user actions.
                if changed.status is DeniedStatus:
                    listing.focus()
                    await pilot.press('end')
                    await pilot.pause()
                    assert await pilot.click('#approve')
                    await until(pilot, lambda: isinstance(app.screen, MCPDecisionScreen))
                    modal = app.screen
                    terminal = modal.query_one(Terminal)
                    await until(pilot, lambda: ' to apply:' in '\n'.join(line.content.plain for line in terminal.state.buffer.lines))
                    terminal.focus()
                    app._driver.send_message(events.Paste(f'approve:{changed.id}:{changed.digest}'))
                    await pilot.pause()
                    await pilot.press('enter')
                    await until(pilot, lambda: 'CLI exited zero' in viewport_text(modal.query_one('#mcp-decision-status', Static)))
                    await pilot.click('#cancel')
                    await until(pilot, lambda: app.screen is screen and screen._inventory is not None)
                if command.declared_name == 'ask':
                    assert changed.call_policy is AskPolicy
                if command.declared_name == 'allow':
                    assert changed.call_policy is AllowPolicy
            pty = LocalDecisionPTY()
            async def unexpected(text):
                raise AssertionError('Stale snapshot launched child')
            # Approved-only command must be eligible in its captured snapshot.
            print('PASS declaration-only new command discovered/clicked/painted/applied without consumer roster', file=sys.__stdout__, flush=True)
            prior = screen._inventory
            prior_row = next(row for row in prior.rows if row.scope.declared_name == 'project')
            package_setup(package, project, agent_dir, trusted=False)
            outcome = await pty.run(selection=MCPSelection(prior, prior_row), command=AllowCommand(),
                                    show=unexpected, controller_visible=lambda: True)
            assert isinstance(outcome, StaleSnapshotOutcome)
            assert pty._process is None
            print('PASS actual changed snapshot refused before child launch', file=sys.__stdout__, flush=True)
            package_setup(package, project, agent_dir, trusted=True)
            await pilot.click('#refresh')
            await until(pilot, lambda: screen._inventory is not None)
            listing.focus()
            await pilot.press('end')
            await pilot.pause()
            await pilot.click('#deny')
            await until(pilot, lambda: isinstance(app.screen, MCPDecisionScreen))
            modal = app.screen
            terminal = modal.query_one(Terminal)
            await until(pilot, lambda: ' to apply:' in '\n'.join(line.content.plain for line in terminal.state.buffer.lines))
            await pilot.resize_terminal(105, 38)
            await pilot.press('escape')
            await until(pilot, lambda: app.screen is screen and screen._inventory is not None and modal._pty._process is None)
            assert next(row for row in screen._inventory.rows if row.scope.declared_name == 'project').status is ApprovedStatus
            print('PASS focused-terminal Escape after resize cancels/reaps without changing ledger', file=sys.__stdout__, flush=True)
            await pilot.press('escape')
            assert not isinstance(app.screen, MCPInventoryScreen)
            assert app._exception is None
        faulthandler.cancel_dump_traceback_later()
        print('PASS continuous actual UI: trust/refusal, shadowing/redaction, all declared decision buttons, challenge keyboard/ledger/refresh, stale snapshot, resized cancel + child reaping', file=sys.__stdout__, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
