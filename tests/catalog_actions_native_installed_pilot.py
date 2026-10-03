"""One continuous installed catalog/editor/PTY/native launch journey."""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import shlex
import sys
import tomllib
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual import widgets
from toad.agent_schema import AgentDefinition
from toad.catalog_actions import CatalogCommandAction
from toad.screens.action_modal import ActionModal
from toad.screens.agent_modal import AgentModal
from toad.screens.command_edit_modal import CommandEditModal
from toad.screens.store import StoreScreen, AgentItem, LauncherItem, LauncherGridSelect
from toad.native_themes import ThemeChoice
from runtime_fixture import ToadApp
from l0a_native_installed_pilot import main, until, response_painted


class AuditAction(CatalogCommandAction):
    """A declaration-only new case, without changing any catalog consumer."""
    def finished(self, modal, return_code):
        modal.query_one('#run-action', widgets.Button).label = f"AUDIT_{return_code}"


def fixture_file():
    return Path(str(files('toad.data').joinpath('agents', 'zz-private-catalog.toml')))


def seed_installed_catalog():
    """Actual configuration data in this fixture's owned installed prefix."""
    destination = fixture_file()
    prefix = Path(os.environ['CATALOG_INSTALLED_PREFIX']).resolve()
    assert destination.resolve().is_relative_to(prefix)
    definition = {
        'identity': 'native-fixture', 'name': 'A native catalog control',
        'short_name': 'native-control', 'protocol': 'acp', 'type': 'coding',
        'author_name': 'Private controlled acceptance',
        'description': 'Local commands and original native saved metadata only',
        'help': '# Native catalog control\nPrivate controlled command data.',
    }
    text = ''.join(f'{key} = {json.dumps(value)}\n' for key, value in definition.items())
    text += '\n[run_command]\n"*" = ' + json.dumps(shlex.join([sys.executable, '-m', 'agent_comms.acp'])) + '\n'
    # Exact platform must win over the wildcard. Neither branch runs an installer.
    text += '\n[actions."*".install]\ndescription = "Wrong platform"\ncommand = "exit 91"\n'
    commands = {
        'install': ('Install local control', 'printf CMD_INSTALL_ORIGINAL; exit 7'),
        'install-acp': ('Install ACP local control', 'printf CMD_ADAPTER_OK'),
        'login': ('Login local control', 'printf CMD_LOGIN_OK'),
        'owner-custom-script': ('Run arbitrary script', 'printf CMD_CUSTOM_OK'),
        'hold': ('Cancel held local command', 'printf CMD_HELD; sleep 30'),
        'audit': ('Declaration-only audit', 'printf CMD_AUDIT_OK'),
    }
    import toad
    for name, (label, command) in commands.items():
        text += f'\n[actions.{json.dumps(toad.os)}.{json.dumps(name)}]\n'
        text += f'description = {json.dumps(label)}\ncommand = {json.dumps(command)}\n'
    if destination.exists():
        assert destination.read_text() == text, 'Never overwrite a different catalog entry'
    else:
        destination.write_text(text)


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')

    def __init__(self, *args, catalog_only=False, **kwargs):
        # Use the same real catalog definition in the initial native session and
        # Store. Saved SessionMeta therefore exercises the unchanged public form.
        if not catalog_only:
            kwargs['agent_data'] = AgentDefinition.decode(tomllib.loads(fixture_file().read_text()))
        super().__init__(*args, **kwargs)

    async def on_load(self):
        self.settings.ui.theme = ThemeChoice.decode('textual-dark')
        await super().on_load()


def frame(app):
    return '\n'.join(strip.text for strip in app.screen._compositor.render_strips())


async def choose(pilot, modal, name):
    import toad
    order = list(modal.agent.commands_for(toad.os))
    index = len(order) if name is None else order.index(name)
    modal.action_select.focus()
    await pilot.press('enter', 'home', *(['down'] * (index + 1)), 'enter')
    await pilot.pause()
    operation = modal.action_select.value
    if name is not None:
        assert operation.name == name, (name, operation)
        assert operation.command is modal.agent.commands_for(toad.os)[name]
        if name == 'audit':
            assert isinstance(operation, AuditAction)
    assert await pilot.click(modal.query_one('#run-action', widgets.Button))


async def open_item(app, pilot, item):
    """A native GridSelect click opens an already highlighted item immediately."""
    item.scroll_visible(immediate=True)
    await pilot.pause()
    assert await pilot.click(item.query_one('#name', widgets.Label))
    await pilot.pause()
    if isinstance(app.screen, StoreScreen):
        await pilot.press('enter')
    await until(pilot, lambda: isinstance(app.screen, AgentModal))


async def execute(app, pilot, name, *, edited=None, cancel=False, expected=0):
    modal = app.screen
    assert isinstance(modal, AgentModal)
    await choose(pilot, modal, name)
    await until(pilot, lambda: isinstance(app.screen, CommandEditModal))
    editor = app.screen
    if edited is not None:
        editor.text_area.focus()
        await pilot.press('f7', *list(edited))
        assert editor.text_area.text == edited, editor.text_area.text
    assert await pilot.click(editor.query_one('#ok', widgets.Button))
    if name == 'login' and expected == 0:
        await until(pilot, lambda: isinstance(app.screen, AgentModal))
        return
    await until(pilot, lambda: isinstance(app.screen, ActionModal))
    executor = app.screen
    pane = executor.command_pane
    if cancel:
        await pilot.pause(.5)
        evidence = Path(os.environ['L0A_EVIDENCE'])
        (evidence / 'held-pty-frame.txt').write_text(frame(app))
        app.save_screenshot(str(evidence / 'held-pty.svg'))
        await until(pilot, lambda: frame(app).count('CMD_HELD') >= 2)
        assert await pilot.click(executor.query_one('#cancel', widgets.Button))
    else:
        await until(pilot, lambda: not executor.ok_button.disabled)
        assert executor.command_pane.return_code == expected
        app.save_screenshot(str(Path(os.environ['L0A_EVIDENCE']) / f'command-{name}-exit{expected}.svg'))
        assert await pilot.click(executor.ok_button)
    await until(pilot, lambda: app.screen is modal)
    assert pane._process is not None and pane._process.returncode is not None
    assert pane._execute_task.done(), 'Native command reader survives its completed dialog'


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    evidence = Path(os.environ['L0A_EVIDENCE'])
    view = app.selected_session.conversation
    original_mode = app.selected_mode
    release.set(); hold_next.clear()
    view.prompt.text = 'NEW_CATALOG_CONTROL_' + evidence.name
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_1'), 30)
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    original_process = comms.registry.require('beta').process_identity
    await agent.session.reconnect()
    await until(pilot, agent.session.settled.is_set)
    await until(pilot, lambda: view.agent_ready and response_painted(app, view, 'NATIVE_RESPONSE_1'))
    assert len(requests) == 1
    assert comms.registry.require('beta').process_identity == original_process
    print('CATALOG_SAVED_NATIVE_ATTACHED', flush=True)
    view.prompt.text = 'KEEP_CATALOG_DRAFT'
    document = view.prompt.prompt_text_area.document
    undo = view.prompt.prompt_text_area.history
    view.window.focus()
    await pilot.press('ctrl+h')
    await until(pilot, lambda: isinstance(app.screen, StoreScreen))
    store = app.screen
    await until(pilot, lambda: any(item.agent.identity == 'native-fixture' for item in store.query(AgentItem)))
    item = next(item for item in store.query(AgentItem) if item.agent.identity == 'native-fixture')
    await open_item(app, pilot, item)
    modal = app.screen
    assert modal.query_one('#run-action', widgets.Button).disabled
    assert 'requires an ACP adapter' in frame(app)
    assert modal.agent is store.agents['native-fixture']
    original_command = modal.agent.commands_for(__import__('toad').os)['install']
    app.save_screenshot(str(evidence / 'catalog-options.svg'))
    print('CATALOG_ACTUAL_GRID_MODAL', flush=True)

    # Editor cancellation admits no command and changes no original source.
    await choose(pilot, modal, 'install')
    await until(pilot, lambda: isinstance(app.screen, CommandEditModal))
    assert await pilot.click(app.screen.query_one('#cancel', widgets.Button))
    await until(pilot, lambda: app.screen is modal)
    assert not modal.launcher_checkbox.value
    await execute(app, pilot, 'install', expected=7)
    assert not modal.launcher_checkbox.value
    await execute(app, pilot, 'install', edited='printf CMD_INSTALL_EDITED')
    await until(pilot, lambda: modal.launcher_checkbox.value)
    assert original_command.command == 'printf CMD_INSTALL_ORIGINAL; exit 7'
    assert modal.agent.identity in app.settings.launcher.agents.splitlines()
    await execute(app, pilot, 'install-acp')
    await execute(app, pilot, 'owner-custom-script')
    await execute(app, pilot, 'hold', cancel=True)
    await execute(app, pilot, 'audit')
    await until(pilot, lambda: 'AUDIT_0' in frame(app))
    app.save_screenshot(str(evidence / 'declaration-completion.svg'))
    await execute(app, pilot, 'login', edited='exit 5', expected=5)
    await execute(app, pilot, 'login')
    print('CATALOG_EDITOR_PTY_COMPLETION_CONTROLS_PASSED', flush=True)
    assert len(requests) == 1
    # Selector launch hands the original framework message to Store's grid path.
    await choose(pilot, modal, None)
    await until(pilot, lambda: app.selected_mode not in {original_mode, 'store'})
    launched = app.selected_session.conversation
    await until(pilot, lambda: launched.agent_ready, 30)
    assert launched.agent.definition.identity == modal.agent.identity
    assert len(requests) == 1, 'No prompt is sent by catalog launch'
    app.save_screenshot(str(evidence / 'catalog-native-launch.svg'))
    print('CATALOG_ORIGINAL_MESSAGE_NATIVE_LAUNCH_PASSED', flush=True)

    await app.select_session(original_mode)
    assert app.selected_session.conversation is view
    assert view.prompt.text == 'KEEP_CATALOG_DRAFT'
    assert view.prompt.prompt_text_area.document is document
    assert view.prompt.prompt_text_area.history is undo
    assert comms.registry.require('beta').process_identity == original_process
    view.window.focus()
    await pilot.press('ctrl+h')
    await until(pilot, lambda: isinstance(app.screen, StoreScreen))
    store = app.screen
    await until(pilot, lambda: any(item.agent.identity == 'native-fixture' for item in store.query(LauncherItem)))
    item = next(item for item in store.query(LauncherItem) if item.agent.identity == 'native-fixture')
    await open_item(app, pilot, item)
    app.save_screenshot(str(evidence / 'launcher-detail.svg'))
    await pilot.press('escape')
    await until(pilot, lambda: isinstance(app.screen, StoreScreen))
    # The third existing consumer is exposed as a native action, without a
    # default key binding. Invoke that actual framework action after real focus.
    grid = store.query_one(LauncherGridSelect)
    grid.focus()
    await grid.run_action('details')
    await until(pilot, lambda: isinstance(app.screen, AgentModal))
    assert app.screen.agent is store.agents['native-fixture']
    await pilot.press('escape')
    await until(pilot, lambda: isinstance(app.screen, StoreScreen))
    assert len(requests) == 1 and app._exception is None
    (evidence / 'catalog-receipt.json').write_text(json.dumps({
        'native_requests': len(requests), 'paid_calls': 0,
        'original_saved_definition_format': True, 'original_command_identity': True,
        'exact_platform_choice': True, 'editor_cancel': True, 'edited_command_no_source_mutation': True,
        'failed_install_no_launcher': True, 'successful_install_launcher': True,
        'external_hyphen_adapter_id': True, 'arbitrary_external_id': True,
        'pty_cancel': True, 'declaration_only_new_case': True,
        'login_failure_explicit_ok_success_auto_close': True,
        'grid_native_launch_no_prompt': True, 'launcher_pointer_detail': True,
        'third_detail_route': 'existing native run_action(details), no default key binding',
        'original_native_process_draft_document_undo': True,
        'installed_toad': __import__('toad').__file__, 'original_owner': str(original_process),
    }, indent=2) + '\n')


async def catalog_only_main():
    """The existing native catalog/editor/PTY journey without a Pi admission."""
    evidence = Path(os.environ['L0A_EVIDENCE'])
    temporary_parent = Path(os.environ['TOAD_CATALOG_PRIVATE'])
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temporary_parent, prefix='catalog-') as temporary:
        root = Path(temporary)
        config = root / 'config' / 'toad'
        config.mkdir(parents=True)
        (config / 'toad.json').write_text(json.dumps({
            'anon_id': '00000000-0000-0000-0000-000000000001',
            'statistics': {'allow_collect': False},
        }))
        with patch.dict(os.environ, XDG_CONFIG_HOME=str(root / 'config'),
                        XDG_STATE_HOME=str(root / 'state'), XDG_DATA_HOME=str(root / 'data'),
                        AGENT_COMMS_ROOT=str(root / 'wire')):
            app = InstalledApp(catalog_only=True, mode='store', project_dir=str(root))
            async with app.run_test(size=(140, 48)) as pilot:
                await until(pilot, lambda: isinstance(app.screen, StoreScreen))
                store = app.screen
                await until(pilot, lambda: any(item.agent.identity == 'native-fixture'
                                              for item in store.query(AgentItem)))
                agent = store.agents['native-fixture']
                item = next(item for item in store.query(AgentItem)
                            if item.agent is agent)
                from toad.agent_schema import ChatAgentKind
                expected_chat = {entry.identity for entry in store.agents.values()
                                 if entry.kind.section() is ChatAgentKind}
                actual_chat = {entry.agent.identity for entry in store.query(AgentItem)
                               if entry.agent.kind.section() is ChatAgentKind}
                assert actual_chat == expected_chat
                chat_headings = [heading for heading in store.query('.heading')
                                 if ChatAgentKind.heading in str(heading.render())]
                assert len(chat_headings) == bool(expected_chat)
                app.save_screenshot(str(evidence / 'catalog-sections.svg'))
                await open_item(app, pilot, item)
                modal = app.screen
                original_command = agent.commands_for(__import__('toad').os)['install']
                await choose(pilot, modal, 'install')
                await until(pilot, lambda: isinstance(app.screen, CommandEditModal))
                assert await pilot.click(app.screen.query_one('#cancel', widgets.Button))
                await until(pilot, lambda: app.screen is modal)
                await execute(app, pilot, 'install', expected=7)
                assert not modal.launcher_checkbox.value
                await execute(app, pilot, 'install', edited='printf CMD_INSTALL_EDITED')
                await until(pilot, lambda: modal.launcher_checkbox.value)
                assert original_command.command == 'printf CMD_INSTALL_ORIGINAL; exit 7'
                await execute(app, pilot, 'install-acp')
                await execute(app, pilot, 'owner-custom-script')
                await execute(app, pilot, 'audit')
                assert 'AUDIT_0' in frame(app)
                await execute(app, pilot, 'login', edited='exit 5', expected=5)
                await execute(app, pilot, 'login')
                await execute(app, pilot, 'hold', cancel=True)
                app.save_screenshot(str(evidence / 'catalog-return.svg'))
                await pilot.press('escape')
                await until(pilot, lambda: app.screen is store)
                assert store.agents['native-fixture'] is agent and app._exception is None
                (evidence / 'catalog-only-receipt.json').write_text(json.dumps({
                    'installed_toad': __import__('toad').__file__,
                    'original_kind_grouping': True, 'original_command_identity': True,
                    'actual_selector_editor_cancel': True, 'real_pty_exit7': True,
                    'edited_command_source_unchanged': True, 'hyphen_id_member': True,
                    'arbitrary_id_explicit_completion': True, 'declaration_new_case': True,
                    'login_failure_explicit_success_auto_close': True, 'real_pty_cancel': True,
                    'same_store_catalog_on_return': True, 'native_pi_inputs': 0,
                    'provider_calls': 0,
                    'scope': 'Installed App/Pilot/catalog/editor/real shell PTY, not physical st/ACP/Pi/authentication',
                }, indent=2) + '\n')
    print('CATALOG_EXISTING_OWNER_INSTALLED_APP_PTY_PASS', flush=True)


if __name__ == '__main__':
    destination = fixture_file()
    original = destination.read_bytes() if destination.exists() else None
    try:
        seed_installed_catalog()
        if '--catalog-only' in sys.argv:
            asyncio.run(asyncio.wait_for(catalog_only_main(), 50))
        else:
            asyncio.run(asyncio.wait_for(main(app_type=InstalledApp, acceptance=acceptance,
                provider_request_budget=1, fixture_stage=os.environ['CATALOG_FIXTURE_STAGE']), 115))
    finally:
        if original is None:
            destination.unlink(missing_ok=True)
        else:
            assert destination.read_bytes() == original
