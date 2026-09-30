"""Actual retained Sol/high SDK fork, installed Toad/ACP/Pi and resource custody.

Only fixture-owned inputs are sent. The public owner and retained original file
are read only. Launch credentials remain in memory and are never saved here.
"""
import asyncio
import json
import os
import shlex
import sys
import time
import traceback
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.goal_attempts import GoalAttemptStore
from agent_comms.input_disposition import InputDispositions
from agent_comms.native_fork import ForkSessionHelper, ForkSessionRequest
from agent_comms.native_package import verify_native_package
from agent_comms.owner_launch import RetainedOwnerLaunch
from agent_comms.registration import Registration
from agent_comms.threads import Thread
from agent_comms.turn_phase import ToolRunningPhase
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory
from l0a_native_installed_pilot import until, response_painted
from runtime_fixture import ToadApp as FixtureApp, stop_test_children
from saved_state_user_journey_pilot import screen_paint, submit_editor


class ResourceJourneyApp(ToadApp):
    CSS_PATH = FixtureApp.CSS_PATH

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = []

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if renderable is not None and not self._batch_count and screen is self.screen:
            view = self.selected_session.conversation
            if view is not None:
                self.frames.append({
                    'elapsed': round(time.monotonic() - self.began, 3),
                    'phase': view.turns.owner.state.phase.declared_name,
                    'paint': screen_paint(self),
                })


def disposition_rows(service):
    return InputDispositions(service.root / InputDispositions.filename).read().rows


async def main():
    assert os.environ['AC_REAL_PROVIDER_AUTHORIZED'] == 'Sol/high retained acceptance'
    stage = Path(os.environ['AC_REAL_FIXTURE_STAGE'])
    evidence = Path(os.environ['L0A_EVIDENCE'])
    assert stage.is_relative_to('/home/ts/wt')
    stage.mkdir(parents=True, exist_ok=False)
    evidence.mkdir(parents=True, exist_ok=True)
    snapshot = Registration(Path(os.environ['AC_REAL_SOURCE_ROOT']) / 'registry.json').snapshot()
    source = snapshot.require_active(os.environ['AC_REAL_SOURCE_OWNER'])
    retained = RetainedOwnerLaunch.capture(source, snapshot)
    assert 'sol' in source.model.lower() and source.thinking_level.declared_name == 'high'
    original = Path(os.environ.get('AC_REAL_SOURCE_FILE', source.session_file))
    assert original.stat().st_size >= 40_000_000
    package = Path(os.environ['AC_NATIVE_COPIED_PACKAGE'])
    verify_native_package(package)
    project = stage / 'project'
    project.mkdir()
    identity = await ForkSessionHelper.run(
        ForkSessionRequest(str(package), str(original), str(project)), cwd=project,
        env=dict(retained.environment, PI_CODING_AGENT_DIR=str(stage / 'native-forks')),
    )
    assert Path(identity.session_file).is_relative_to(stage)
    service = Comms(stage / 'wire')
    root_id = service.messaging.initialize_private_initial_protocol()
    service.owners.pin_private_nk_launch(service.root, root_id, package)
    runtime = Path(sys.executable).parent
    environment = dict(retained.environment)
    environment.update(
        AGENT_COMMS_ROOT=str(service.root), AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
        AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
        AGENT_COMMS_AGENT_BIN=str(runtime / 'pi-comms-native'),
        AGENT_COMMS_AGENT_ARGS=shlex.join(retained.arguments or ()),
        PATH=str(runtime) + os.pathsep + environment.get('PATH', ''),
        VIRTUAL_ENV=str(runtime.parent), AGENT_COMMS_RUNTIME_ROOT=str(runtime),
        AGENT_COMMS_DEBUG_LOG=str(stage / 'acp-debug'),
        XDG_CONFIG_HOME=str(stage / 'config'), XDG_STATE_HOME=str(stage / 'state'),
        XDG_DATA_HOME=str(stage / 'data'), TOAD_TEST_ATTEMPT=stage.name,
    )
    for key in ('PI_PROMPT', 'PI_PARENT_ID', 'PI_TASK', 'PI_AGENT_ID',
                'AGENT_COMMS_THREAD', 'AGENT_COMMS_STARTUP_INPUT_KEY', 'PYTHONPATH'):
        environment.pop(key, None)
    os.environ.clear()
    os.environ.update(environment)
    service.registry.declare(Thread(
        'resource436', frozenset(), str(project), session_file=identity.session_file,
        model=source.model, thinking_level=source.thinking_level,
        task='Isolated bounded lifecycle acceptance only. Never resume inherited work. '
             'Use only explicitly requested acceptance tools and fixture goal. '
             'All paths and goals belong to this private fixture.',
    ))
    definition = AgentDefinition.decode({
        'name': 'Real resource acceptance', 'identity': 'real-resource436',
        'short_name': 'resource', 'protocol': 'acp',
        'run_command': {'*': shlex.join([sys.executable, '-m', 'agent_comms.acp'])},
    })
    app = ResourceJourneyApp(agent_data=definition, project_dir=str(project),
                             agent_session_id='resource436')
    app.began = time.monotonic()
    receipt = {'provider': source.model, 'thinking': source.thinking_level.declared_name,
               'original_bytes': original.stat().st_size, 'original_inputs_replayed': 0,
               'completed_phases': [], 'core': '82ba0856', 'toad': 'e21363c8'}

    async def cancel_tool(pilot, view, marker):
        await until(pilot, lambda: (project / marker).exists(), 120)
        owner = service.registry.require('resource436')
        assert isinstance(owner.active_turn.phase, ToolRunningPhase)
        receipt.setdefault('cancelled_turns', []).append(owner.active_turn.id)
        app.save_screenshot(str(evidence / f'{marker}-running.svg'))
        await pilot.press('escape', 'escape')
        await until(pilot, lambda: not service.registry.require('resource436').executing
                    and view.agent.presentation.prompt_in_flight == 0, 30)
        await until(pilot, lambda: 'Native input started; turn cancelled' in screen_paint(app), 10)
        app.save_screenshot(str(evidence / f'{marker}-cancelled.svg'))
        assert not (project / f'{marker}-finished').exists(), 'Cancelled tool continued its side effect'

    async def fresh_reply(pilot, view, token):
        before = set(disposition_rows(service))
        await submit_editor(pilot, view.prompt.prompt_text_area,
                            f'New isolated acceptance input. No tools. Reply exactly {token}.')
        await until(pilot, lambda: any(token in row.source_text and row.has_started
                    for row in disposition_rows(service).values()), 120)
        await until(pilot, lambda: not service.registry.require('resource436').executing
                    and view.agent.presentation.prompt_in_flight == 0, 120)
        await pilot.press('end')
        await until(pilot, lambda: response_painted(app, view, token), 20)
        new = {key: row for key, row in disposition_rows(service).items() if key not in before}
        assert len(new) == 1 and all(row.has_started for row in new.values())
        receipt.setdefault('fresh_inputs', []).append([row.public() for row in new.values()])

    try:
        async with app.run_test(size=(160, 44)) as pilot:
            view = app.selected_session.conversation
            await until(pilot, lambda: view.agent is not None and view.agent_ready, 50)
            await until(pilot, lambda: bool(view.contents.query(TranscriptHistory)), 30)
            receipt['completed_phases'].append('original_saved_history_open')
            command = f'printf started > {project}/ordinary-running; sleep 35; touch {project}/ordinary-running-finished'
            await submit_editor(pilot, view.prompt.prompt_text_area,
                'Isolated acceptance. Do not resume inherited work. Use bash exactly once '
                f'to execute this command: {command}. This tool will be interrupted from the UI.')
            await cancel_tool(pilot, view, 'ordinary-running')
            receipt['completed_phases'].append('actual_tool_interrupt_settled')
            await fresh_reply(pilot, view, 'RESOURCE436_NEXT_INPUT_OK')
            receipt['completed_phases'].append('same_open_next_input_answered')
            command = f'printf started > {project}/goal-running; sleep 35; touch {project}/goal-running-finished'
            await submit_editor(pilot, view.prompt.prompt_text_area,
                'Explicit isolated acceptance request: call comms_set_goal to set the goal '
                'text RESOURCE436_GOAL_ORIGINAL. Then call comms_edit_goal with that exact '
                'returned goal ID and text RESOURCE436_GOAL_EDITED. Finally use bash exactly '
                f'once to execute: {command}. Do not complete or block the goal yourself; '
                'the UI will cancel this tool to verify canonical failed-goal settlement.')
            await cancel_tool(pilot, view, 'goal-running')
            goal = service.registry.require('resource436').goal
            assert goal is not None and goal.text == 'RESOURCE436_GOAL_EDITED'
            assert goal.state.declared_name == 'blocked', goal
            generation = GoalAttemptStore(service.root / 'goal-private').snapshot(goal.id)
            assert generation is not None and generation.lifecycle.failed, generation
            receipt['goal'] = FieldCodec.encode(goal)
            receipt['goal_generation'] = FieldCodec.encode(generation)
            receipt['completed_phases'].append('actual_goal_edit_cancel_failed_settlement')
            await fresh_reply(pilot, view, 'RESOURCE436_BLOCKED_GOAL_NEXT_INPUT_OK')
            assert service.registry.require('resource436').goal == goal
            receipt['completed_phases'].append('blocked_goal_preserved_ordinary_input_answered')
            assert len(disposition_rows(service)) == 4, 'A fixture input was replayed'
            assert all(row.has_started for row in disposition_rows(service).values())
            assert app._exception is None
            receipt['complete'] = True
    except BaseException:
        (evidence / 'failure.txt').write_text(traceback.format_exc())
        raise
    finally:
        receipt['inputs'] = [row.public() for row in disposition_rows(service).values()]
        receipt['elapsed_seconds'] = round(time.monotonic() - app.began, 3)
        (evidence / 'visible-frames.json').write_text(json.dumps(app.frames))
        for owner in service.registry.all_threads().values():
            if owner.role.executable and owner.process_alive:
                await asyncio.to_thread(service.owners.stop, owner.name)
        await stop_test_children(stage.name)
        receipt['children_retired'] = all(not owner.process_alive
            for owner in service.registry.all_threads().values())
        (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print('REAL_RESOURCE_CUSTODY_ACCEPTANCE', json.dumps(receipt), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
