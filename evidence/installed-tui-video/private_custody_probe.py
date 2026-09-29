"""Extend the existing native fixture; no substitute app, store or transport."""
import asyncio
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

TESTS = Path(os.environ['VIDEO_FIXTURE_TESTS'])
sys.path.insert(0, str(TESTS))
from l0a_native_installed_pilot import main as native_fixture, until
from saved_state_user_journey_pilot import prepare_saved_state, SavedStateSubscriber
from native_session_retention_pilot import InstalledApp, conversation_paint
from agent_comms.acp import CommsClient
from acp.schema import TextContentBlock

ROOT = Path(os.environ['L0A_EVIDENCE'])
TOOL = Path(__file__).resolve().parents[2] / 'tests/tools/record_installed_tui.py'
# __file__ is evidence/installed-tui-video, parents[2] is repository root.
REPORT = {'assessment': 'unreviewed', 'captures': [], 'owner_checks': []}


def owner_check(comms, before, label):
    observed = {}
    for name, identity in before.items():
        current = comms.registry.require(name)
        assert current.process_identity == identity and identity.alive(), (name, current)
        observed[name] = {'pid': identity.pid, 'start_ticks': identity.start_time, 'alive': True}
    REPORT['owner_checks'].append({'label': label, 'owners': observed})
    (ROOT / 'custody-acceptance.json').write_text(json.dumps(REPORT, indent=2) + '\n')


async def capture(comms, project, label, before, *, actions=None, profile=False):
    runtime = Path(sys.prefix) / 'bin'
    env = os.environ.copy()
    env['AGENT_COMMS_RUNTIME_ROOT'] = str(runtime)
    command = [str(runtime / 'toad'), 'acp', shlex.join([sys.executable, '-m', 'agent_comms.acp']), str(project), '--session', 'beta']
    argv = [sys.executable, str(TOOL), '--owner', 'Mendel', '--private-root', str(comms.root), '--fit-window', '--startup-wait', '10', '--max-duration', '60' if actions else '17', '--tail-seconds', '1', '--review-seconds', '5' if actions else '1', '--review-frames', '40', '--output', str(ROOT / label)]
    if actions:
        argv += ['--actions', str(actions)]
        for phase in ['warm-a', 'warm-b', 'warm-return', 'up', 'down', 'reverse', 'end', 'idle']:
            argv += ['--review-phase', phase]
    if profile:
        argv += ['--profile', '--profile-rate', '25']
    argv += ['--', *command]
    print('PRIVATE_CAPTURE_COMMAND', shlex.join(argv), flush=True)
    await asyncio.to_thread(subprocess.run, argv, env=env, check=True, timeout=240)
    receipt = json.loads((ROOT / label / 'receipt.json').read_text())
    assert receipt['completed'] and receipt['cleanup']['remaining_owned_pids'] == [] and receipt['cleanup']['errors'] == []
    assert receipt['assessment'] == 'unreviewed'
    owner_check(comms, before, 'after-' + label)
    REPORT['captures'].append(label)


async def prepare(comms, project, requests, entered, release, hold_next):
    await prepare_saved_state(comms, project, requests, entered, release, hold_next)
    client = CommsClient(comms, runtime_enabled=True,
                         private_nk_native_package=Path(os.environ['AC_NATIVE_COPIED_PACKAGE']),
                         private_nk_wire_root_id=os.environ['AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID'])
    subscriber = SavedStateSubscriber()
    client.on_connect(subscriber)
    try:
        async with asyncio.timeout(25):
            await client.load_session(cwd=str(project), session_id='gamma')
            await client.prompt('gamma', [TextContentBlock(type='text', text='NEW_PRIVATE_GAMMA_HISTORY_SEED')])
        subscriber.require_success()
    finally:
        await client.shutdown()
    before = {name: comms.registry.require(name).process_identity for name in ['beta', 'gamma']}
    assert all(before.values())
    owner_check(comms, before, 'before-capture')
    # Both are separately launched real owners before the terminal attaches.
    await capture(comms, project, 'private-startup', before)
    print('PRIVATE_STARTUP_READY_FOR_PHYSICAL_COORDINATES', flush=True)
    action_path = os.environ.get('VIDEO_ACTIONS')
    if action_path is None:
        import select
        if not select.select([sys.stdin], [], [], 60)[0]:
            raise TimeoutError('No physical action script supplied within private fixture budget')
        action_path = sys.stdin.readline().strip()
    actions = Path(action_path)
    assert actions.is_relative_to(ROOT.parent) and actions.is_file()
    await capture(comms, project, 'private-profiled', before, actions=actions, profile=True)
    await capture(comms, project, 'private-unprofiled', before, actions=actions)
    owner_check(comms, before, 'after-paired-captures')
    # Preserve generated fixture evidence before the existing lifecycle tears
    # down its disposable root. Sockets are runtime handles, not saved state.
    import shutil, stat
    def runtime_handles(directory, names):
        return [name for name in names if not (Path(directory) / name).is_dir()
                and not stat.S_ISREG((Path(directory) / name).lstat().st_mode)]
    shutil.copytree(comms.root, ROOT / 'preserved-wire', ignore=runtime_handles)
    shutil.copytree(project.parent, ROOT / 'preserved-stage', ignore=runtime_handles)
    REPORT['original_owners'] = {n: {'pid': i.pid, 'start_ticks': i.start_time} for n, i in before.items()}
    REPORT['requests_before_attach'] = len(requests)
    (ROOT / 'custody-acceptance.json').write_text(json.dumps(REPORT, indent=2) + '\n')


async def accepted(app, pilot, agent, comms, entered, release, hold_next, requests):
    current = comms.registry.require('beta')
    original = REPORT['original_owners']['beta']
    assert current.process_identity.pid == original['pid'] and current.process_identity.start_time == original['start_ticks']
    assert agent.session.connected and current.process_identity.alive()
    previous = len(requests)
    release.set()
    hold_next.clear()
    await asyncio.wait_for(agent.send_prompt('NEW_PRIVATE_POST_CAPTURE_CUSTODY_INPUT'), 25)
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    await until(pilot, lambda: f'NATIVE_RESPONSE_{previous + 1}' in conversation_paint(app.screen))
    assert len(requests) == previous + 1
    assert comms.registry.require('beta').process_identity == current.process_identity
    REPORT.update(assessment='custody accepted; video assessment separate', attachable_after_capture=True,
                  new_controlled_input_worked=True, provider_requests=len(requests), fixture='existing l0a_native_installed_pilot + prepare_saved_state')
    (ROOT / 'custody-acceptance.json').write_text(json.dumps(REPORT, indent=2) + '\n')
    print('PRIVATE_OWNER_SURVIVED_ATTACHED_AND_NEW_INPUT_WORKED', flush=True)


def reply(request, number):
    content = f'NATIVE_RESPONSE_{number}\n\n' + '\n\n'.join(f'Reader paragraph {i:03d}: real retained native response {number}, preparation and scrolling evidence.' for i in range(160))
    return {'role': 'assistant', 'content': content}, 'stop'


if __name__ == '__main__':
    asyncio.run(native_fixture(app_type=InstalledApp, prepare_state=prepare, acceptance=accepted,
                              provider_reply=reply, provider_request_budget=4))
