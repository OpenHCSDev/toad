"""Configured saved-helper ACP selectors and A/B/A, with zero native prompts.

The canonical fork helper owns the saved copy; original settings/auth stay in
RAM. Only the disposable child receives configuration requests, never retries.
"""
import asyncio
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys

from agent_comms.comms import Comms, wire
from agent_comms.field_codec import FieldCodec
from agent_comms.native_fork import ForkSessionHelper, ForkSessionRequest
from agent_comms.native_package import verify_native_package
from agent_comms.owner_launch import RetainedOwnerLaunch
from agent_comms.threads import Thread
from l0a_native_installed_pilot import until
from runtime_fixture import ToadApp
from toad.agent_schema import AgentDefinition
from toad.navigation_target import NavigationContext, channel_target
from toad.widgets.prompt import AgentInfo


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


async def main(stage, package, resume=False, continuation='continuation-851'):
    import toad
    assert Path(toad.__file__).is_relative_to(sys.prefix), 'No source overlay'
    if not resume:
        stage.mkdir(mode=0o700, exist_ok=False)
    evidence = stage / continuation if resume else stage
    evidence.mkdir(exist_ok=True)
    verify_native_package(package)
    public = wire()
    snapshot = public.registry.snapshot()
    source = snapshot.require_active('openhcs-helper')
    launch = RetainedOwnerLaunch.capture(source, snapshot)
    original = Path(source.session_file)
    source_hash = digest(original)
    environment = dict(launch.environment)
    config = Path(environment.get('AGENT_COMMS_NATIVE_CONFIG_DIR') or
                  environment.get('PI_CODING_AGENT_DIR') or '~/.pi/agent').expanduser()
    settings = {str(config / name): digest(config / name)
                for name in ('auth.json', 'models.json', 'settings.json') if (config / name).exists()}
    service = Comms(stage / 'wire')
    if resume:
        previous = json.loads((stage / 'receipt.json').read_text())
        from agent_comms.native_session_reopen import NativeSessionIdentity
        fork = FieldCodec.decode(NativeSessionIdentity, previous['canonical_fork'])
        # Recover the identity of this already-created owned fixture, never
        # initialize or rewrite a nonempty root. The reviewed package remains
        # an explicit caller argument and normal launch preflight still runs.
        root_id = service.bus.log.read_metadata_unlocked(required=True).root_id
    else:
        fork = await ForkSessionHelper.run(
            ForkSessionRequest(str(package), str(original), source.worktree),
            cwd=Path(source.worktree),
            env=dict(environment, PI_CODING_AGENT_DIR=str(stage / 'forks')),
        )
        root_id = service.messaging.initialize_private_initial_protocol()
    service.owners.pin_private_nk_launch(service.root, root_id, package)
    runtime = Path(sys.executable).parent
    environment.update(AGENT_COMMS_ROOT=str(service.root),
        AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
        AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
        AGENT_COMMS_NATIVE_CONFIG_DIR=str(config),
        AGENT_COMMS_AGENT_BIN=str(runtime / 'pi-comms-native'),
        AGENT_COMMS_RUNTIME_ROOT=str(runtime),
        AGENT_COMMS_AGENT_ARGS=shlex.join(launch.arguments),
        PATH=str(runtime) + os.pathsep + environment.get('PATH', ''),
        VIRTUAL_ENV=str(runtime.parent),
        AGENT_COMMS_DEBUG_LOG=str(stage / 'acp-debug'),
        XDG_CONFIG_HOME=str(stage / 'config'), XDG_STATE_HOME=str(stage / 'state'),
        XDG_DATA_HOME=str(stage / 'data'), TOAD_TEST_ATTEMPT=stage.name)
    for key in ('PI_PROMPT', 'PI_PARENT_ID', 'PI_TASK', 'PI_AGENT_ID',
                'AGENT_COMMS_THREAD', 'AGENT_COMMS_STARTUP_INPUT_KEY', 'PYTHONPATH'):
        environment.pop(key, None)
    os.environ.clear()
    os.environ.update(environment)
    child = Thread('selection302', source.tags, source.worktree, parent=source.name,
        task=source.task, session_file=fork.session_file, model=source.model,
        thinking_level=source.thinking_level, execution=source.execution)
    if not resume:
        service.registry.declare(child)
    definition = AgentDefinition.decode({'name': 'Configured selection acceptance',
        'identity': 'selection302', 'protocol': 'acp',
        'run_command': {'*': shlex.join([sys.executable, '-m', 'agent_comms.acp'])}})
    receipt = {'prefix': sys.prefix, 'native': str(package), 'source_owner': source.name,
        'source_process': FieldCodec.encode(launch.process), 'source_interpreter': launch.interpreter,
        'source_session': str(original), 'source_session_sha256_observed': source_hash,
        'source_bytes': original.stat().st_size, 'canonical_fork': FieldCodec.encode(fork),
        'model': source.model, 'thinking': source.thinking_level.declared_name,
        'worktree': source.worktree, 'settings_hashes': settings,
        'native_prompts': 0, 'public_inputs': 0, 'root_id': root_id, 'completed': []}

    def persist(phase):
        receipt['completed'].append(phase)
        (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(phase, flush=True)

    app = InstalledApp(project_dir=source.worktree, agent_data=definition,
                       agent_session_id=child.name)
    agent = None
    try:
        if resume:
            # Prior fixture teardown deliberately stopped this private owner.
            # Use its explicit lifecycle start; ensuring-load cannot undo stop.
            started = service.owners.start(child.name, agent_bin=str(runtime / 'pi-comms-native'),
                                           agent_args=launch.arguments)
            receipt['private_start'] = FieldCodec.encode(started)
            persist('explicit-owned-fixture-reopen-from-fresh-retained-launch')
        async with app.run_test(size=(150, 44)) as pilot:
            view = app.selected_session.conversation
            await until(pilot, lambda: view.agent is not None and view.agent_ready, 60)
            agent = view.agent
            await until(pilot, lambda: agent.configuration.model.selected is not None)
            assert agent.configuration.model.current == source.model
            assert view.prompt.agent is agent
            persist('ordinary-configured-saved-native-ACP-loaded')
            view.prompt.text = 'SELECTION302_UNSENT_DRAFT'
            document = view.prompt.prompt_text_area.document
            undo = view.prompt.prompt_text_area.history
            if not continuation.startswith(('navigation-only-', 'reconnect-only-')):
                assert await pilot.click(view.prompt.query_one(AgentInfo))
                picker = view.prompt.model_switcher
                await until(pilot, lambda: picker.is_open and picker.search_input.has_focus)
                picker.search_input.value = source.model
                await pilot.pause()
                choices = picker.option_list
                index = choices.get_option_index(source.model)
                assert choices.get_option_at_index(index).id == agent.configuration.model.selected.value
                choices.highlighted = index
                await pilot.press('enter')
                from toad.widgets.comms_menu import ContextMenu
                await until(pilot, lambda: not picker.is_open)
                await until(pilot, lambda: isinstance(app.screen, ContextMenu))
                high = next(item for item in app.screen.query('ContextMenuItem') if item.action == 'high')
                await until(pilot, lambda: high in app.screen._compositor.visible_widgets and high.region.width > 0)
                assert await pilot.click(high, offset=(1, 0))
                await until(pilot, lambda: app.screen is view.screen)
                assert agent.configuration.model.current == source.model
                assert service.registry.require(child.name).model == source.model
                persist('actual-model-picker-click-acknowledged-original-selection')
                accepted = agent.configuration.model.option
                error = await agent.set_model('selection302/no-such-advertised-model')
                assert error is not None and agent.configuration.model.option == accepted
                persist('refused-request-left-original-selection-unchanged')
            thinking = agent.configuration.thinking.current
            assert thinking == 'high'
            assert service.registry.require(child.name).thinking_level.declared_name == thinking
            returned = view
            if not continuation.startswith('reconnect-only-'):
                mode = app.selected_mode
                other = await channel_target('#selection302').open(NavigationContext(
                    app, mode, Path(source.worktree), service.messaging.user_identity(source.worktree).name))
                from toad.widgets.session_tabs import SessionsTabs
                receipt['navigation'] = {'from': mode, 'to': other, 'selected': app.selected_mode,
                                         'screen': type(app.screen).__name__, 'mode': app.current_mode,
                                         'stack': [type(screen).__name__ for screen in app.screen_stack]}
                persist('channel-navigation-original-workspace-captured')
                tabs = app.workspace_screen.query_one(SessionsTabs)
                # Existing tab buttons own the actual user navigation requests.
                assert await pilot.click(tabs.query_one(f'#{mode}'))
                await until(pilot, lambda: app.selected_mode == mode)
                returned = app.selected_session.conversation
                assert returned.agent is agent and returned.prompt.agent is agent
                assert returned.prompt.text == 'SELECTION302_UNSENT_DRAFT'
                assert returned.prompt.prompt_text_area.document is document
                assert returned.prompt.prompt_text_area.history is undo
                assert await pilot.click(returned.prompt.query_one(AgentInfo))
                await until(pilot, lambda: returned.prompt.model_switcher.is_open)
                current_row = returned.prompt.model_switcher.option_list.get_option(source.model)
                assert '✓' in str(current_row.prompt)
                await pilot.press('escape')
                persist('physical-A-B-A-original-owner-selection-draft-undo-preserved')
            await agent.session.reconnect()
            await until(pilot, lambda: agent.ready and returned.agent_ready)
            assert agent.configuration.model.current == source.model
            assert agent.configuration.thinking.current == thinking
            assert returned.prompt.agent is agent
            def painted():
                return '\n'.join(strip.text for strip in app.workspace_screen._compositor.render_strips())
            await until(pilot, lambda: agent.configuration.model.selected.name in painted())
            paint = painted()
            (evidence / 'selectors.svg').write_text(app.export_screenshot())
            persist('actual-native-reconnect-current-selection-derived-and-painted')
            with sqlite3.connect(service.root / 'coordination.sqlite3') as db:
                assert db.execute('SELECT count(*) FROM native_runtime_input').fetchone()[0] == 0
            receipt['native_prompts'] = 0
            receipt['configured_source_hashes_unchanged'] = all(digest(Path(path)) == value for path, value in settings.items())
            assert receipt['configured_source_hashes_unchanged']
            assert app._exception is None
            persist('PASS-zero-provider-prompts-no-original-replay')
    except BaseException as error:
        receipt['failure'] = f'{type(error).__name__}: {error}'
        (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        raise
    finally:
        if agent is not None:
            await agent.stop()
        receipt['owned_owner_after'] = FieldCodec.encode(service.registry.require(child.name).process_identity)
        (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1]).absolute(), Path(sys.argv[2]).absolute(), len(sys.argv) > 3,
                     sys.argv[4] if len(sys.argv) > 4 else 'continuation-851'))
