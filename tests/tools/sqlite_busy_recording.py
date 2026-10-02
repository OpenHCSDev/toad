"""Borrow the saved-source fixture and recorder for one private SQL exclusion.

The two FIFOs are owned process input/output resources. They synchronize the
physical driver with Mendel's bounded SQL holder, without editing database rows
or introducing a UI state owner. Native inputs are forbidden by the fixture.
"""
import asyncio
import json
import os
from pathlib import Path
import pickle
import select
import shlex
import subprocess
import sys
import time

from record_installed_tui import (
    PhysicalJourney, ProcessOwner, RetainedLifetimeJourney,
    marker_command, native_click_command, main as record,
)


class SqliteBusyJourney(PhysicalJourney):
    review_artifacts = ('sqlite-busy-review.json',)

    @classmethod
    def script(cls, args):
        marker = marker_command()
        control = 'exec --sync ' + shlex.join([sys.executable, str(Path(__file__).resolve()), '--sql-control'])
        return '\n'.join((
            RetainedLifetimeJourney.ready_command(args, 'native-ready', args.command[-1]),
            native_click_command('phase-native-ready-state.pickle'),
            'keydown Prior', f'sleep {args.scroll_hold_seconds:g}', 'keyup Prior',
            f'sleep {args.navigation_settle_seconds:g}', marker + 'reader',
            control + ' acquire', 'key End', 'sleep 1', marker + 'busy-end',
            control + ' release',
            RetainedLifetimeJourney.ready_command(args, 'released-ready', args.command[-1]),
            f'sleep {args.navigation_settle_seconds:g}', marker + 'settled-end', '',
        ))

    @classmethod
    def review(cls, output, receipt):
        def selected(label):
            snapshot = pickle.loads((output / f'phase-{label}-state.pickle').read_bytes())
            view, = (view for view in snapshot['views'] if view['mode'] == snapshot['metadata']['current_mode'])
            return view
        ready, busy, settled = (selected(label) for label in ('native-ready', 'busy-end', 'settled-end'))
        checks = {
            'same_native_view': ready['agent_configuration']['session_id'] == busy['agent_configuration']['session_id'] == settled['agent_configuration']['session_id'],
            'native_end_held_by_original_work': any(page['source_state'] == 'WorkingTranscript' and page['pending_request'] == 'LatestViewportRequest' for page in busy['history_pages']),
            'native_end_released_without_refresh': all(page['source_state'] != 'WorkingTranscript' for page in settled['history_pages']),
            'saved_history_still_attached': bool(settled['history_pages']),
            'destination_is_native_end': all(abs(window['scroll_y'] - window['maximum']) < 1 for window in settled['history_windows']),
        }
        result = {'checks': checks, 'scope': 'Private native saved history, actual End during SQL exclusion, automatic release; no input or performance claim'}
        (output / 'sqlite-busy-review.json').write_text(json.dumps(result, indent=2) + '\n')
        return result

    @classmethod
    def validate_review(cls, review):
        failed = [name for name, passed in review['checks'].items() if not passed]
        if failed:
            raise RuntimeError('Private native busy recovery failed: ' + ', '.join(failed))


def control(operation):
    directory = Path(os.environ['TOAD_SQL_CONTROL'])
    request = os.open(directory / 'request', os.O_WRONLY)
    reply = os.open(directory / 'reply', os.O_RDONLY)
    try:
        token = {'acquire': b'A', 'release': b'R'}[operation]
        os.write(request, token)
        remaining = float(os.environ['TOAD_VIDEO_DEADLINE']) - time.monotonic()
        if remaining <= 0 or not select.select([reply], [], [], remaining)[0]:
            raise TimeoutError('Owned SQL resource did not acknowledge the physical operation')
        if os.read(reply, 1) != token:
            raise RuntimeError('Owned SQL resource rejected the physical operation')
    finally:
        os.close(request)
        os.close(reply)


async def capture(service, project, evidence, environment):
    output = evidence / 'capture'
    directory = evidence / 'sql-process-input'
    directory.mkdir()
    for name in ('request', 'reply'):
        os.mkfifo(directory / name, 0o600)
    environment['TOAD_SQL_CONTROL'] = str(directory)
    environment.pop('NO_COLOR', None)
    runtime = Path(sys.executable).parent
    command = [str(runtime / 'python'), str(Path(__file__).resolve()),
        '--journey', 'sqlite_busy', '--private-root', str(service.root),
        '--capture-state', '--output', str(output), '--owner', 'Heisenberg537-native-busy',
        '--fit-window', '--width', '1280', '--height', '900', '--startup-wait', '1',
        '--history-wait-seconds', '35', '--navigation-settle-seconds', '1',
        '--max-duration', '160', '--finalize-seconds', '12', '--tail-seconds', '1',
        '--review-timing', 'deferred', '--', str(runtime / 'toad'), 'acp',
        shlex.join([str(runtime / 'python'), '-m', 'agent_comms.acp']), str(project),
        '--title', 'Agent Comms', '--session', 'resource436']
    (evidence / 'record-command.json').write_text(json.dumps(command, indent=2) + '\n')

    def run():
        from agent_comms.registration import Registration
        owner = ProcessOwner(Registration(service.root / 'registry.json'))
        request = os.open(directory / 'request', os.O_RDWR | os.O_NONBLOCK)
        reply = os.open(directory / 'reply', os.O_RDWR | os.O_NONBLOCK)
        holder = None
        try:
            with (evidence / 'recorder.log').open('w') as log, (evidence / 'sql-resource.jsonl').open('wb') as sql:
                recorder = owner.start(command, env=environment, stdout=log, stderr=log)
                print('PHYSICAL_RECORDER', recorder.process.pid, output, flush=True)
                deadline = time.monotonic() + 175
                while recorder.process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Private physical recorder exceeded its owned observation budget')
                    if not select.select([request], [], [], .2)[0]:
                        continue
                    token = os.read(request, 1)
                    if token == b'A':
                        assert holder is None
                        snapshot = pickle.loads((output / 'phase-reader-state.pickle').read_bytes())
                        view, = (view for view in snapshot['views'] if view['mode'] == snapshot['metadata']['current_mode'])
                        assert any(page['has_newer'] for page in view['history_pages']), 'Physical reader has not left the native tail; End would not read storage'
                        holder = owner.start([str(runtime / 'python'), str(SQL_HOLDER), str(service.root)],
                            env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sql)
                        if not select.select([holder.process.stdout], [], [], 5)[0]:
                            raise TimeoutError('Private SQL resource was not acquired')
                        acquired = holder.process.stdout.readline()
                        assert json.loads(acquired)['phase'] == 'exclusive-acquired'
                        sql.write(acquired)
                        sql.flush()
                    elif token == b'R':
                        assert holder is not None
                        holder.process.stdin.write(b'R')
                        holder.process.stdin.flush()
                        out, _ = holder.process.communicate(timeout=5)
                        sql.write(out)
                        sql.flush()
                        assert holder.process.returncode == 0
                    else:
                        raise ValueError('Unknown owned process operation')
                    os.write(reply, token)
                if recorder.process.returncode:
                    raise subprocess.CalledProcessError(recorder.process.returncode, command)
        finally:
            os.close(request)
            os.close(reply)
            (evidence / 'process-cleanup.json').write_text(json.dumps(owner.cleanup(), indent=2) + '\n')
    await asyncio.to_thread(run)


SQL_HOLDER = Path('/home/ts/wt/toad-command-source-closure-20261002/evidence/sqlite407-paired-332-20261002/hold-private-sql.py')

if __name__ == '__main__':
    if sys.argv[1:2] == ['--sql-control']:
        control(sys.argv[2])
    elif sys.argv[1:] == ['--fixture']:
        sys.path[:0] = [str(Path(__file__).resolve().parents[1]), '/home/ts/wt/comms-cleanup-live-integration-20260929/tools/cutover']
        from original_turn_resource_real_installed_pilot import main as fixture
        asyncio.run(fixture(readonly_capture=capture))
    else:
        record()
