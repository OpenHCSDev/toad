"""Reopen owned302 and record one combined installed selector/warm journey."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys

from agent_comms.comms import Comms, wire
from agent_comms.field_codec import FieldCodec
from agent_comms.owner_launch import RetainedOwnerLaunch
from agent_comms.thread_management import ForkSpec
from record_installed_tui import ProcessOwner


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    prefix = Path(sys.prefix)
    fixture = Path(sys.argv[1]).absolute()
    output = Path(sys.argv[2]).absolute()
    package = Path(sys.argv[3]).absolute()
    assert not output.exists()
    output.mkdir(parents=True, mode=0o700)
    public = wire()
    snapshot = public.registry.snapshot()
    original = snapshot.require_active('openhcs-helper')
    launch = RetainedOwnerLaunch.capture(original, snapshot)
    env = dict(launch.environment)
    config = Path(env.get('AGENT_COMMS_NATIVE_CONFIG_DIR') or env.get('PI_CODING_AGENT_DIR') or '~/.pi/agent').expanduser()
    settings = {str(config / name): digest(config / name) for name in ('auth.json', 'models.json', 'settings.json') if (config / name).exists()}
    service = Comms(fixture / 'wire')
    root_id = service.bus.log.read_metadata_unlocked(required=True).root_id
    service.owners.pin_private_nk_launch(service.root, root_id, package)
    runtime = prefix / 'bin'
    env.update(AGENT_COMMS_ROOT=str(service.root), AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
        AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package), AGENT_COMMS_NATIVE_CONFIG_DIR=str(config),
        AGENT_COMMS_AGENT_BIN=str(runtime / 'pi-comms-native'), AGENT_COMMS_RUNTIME_ROOT=str(runtime),
        AGENT_COMMS_AGENT_ARGS=shlex.join(launch.arguments),
        PI_CODING_AGENT_DIR=str(fixture / 'forks'),
        XDG_STATE_HOME=str(output / 'state'), XDG_CONFIG_HOME=str(output / 'config'),
        XDG_DATA_HOME=str(output / 'data'),
        PATH=str(runtime) + os.pathsep + env.get('PATH', ''), VIRTUAL_ENV=str(prefix),
        TOAD_TEST_ATTEMPT='receiving304-combined01')
    for key in ('PI_PROMPT', 'PI_PARENT_ID', 'PI_TASK', 'PI_AGENT_ID', 'AGENT_COMMS_THREAD',
                'AGENT_COMMS_STARTUP_INPUT_KEY', 'PYTHONPATH', 'NO_COLOR'):
        env.pop(key, None)
    os.environ.clear()
    os.environ.update(env)
    receipt = {'prefix': str(prefix), 'fixture': str(fixture), 'public_source_process': FieldCodec.encode(launch.process),
               'public_source_interpreter': launch.interpreter, 'root_id': root_id,
               'settings_hashes': settings, 'native_prompts': 0, 'public_inputs': 0}
    owner = ProcessOwner()
    try:
        started = service.owners.start('selection302', agent_bin=str(runtime / 'pi-comms-native'), agent_args=launch.arguments)
        receipt['private_reopen'] = FieldCodec.encode(started)
        # Real A/B/A native surfaces need separate original source owners.
        # One sibling within the SAME existing private fixture uses canonical
        # ForkSpec/SessionManager, no task/prompt or public-source replay.
        peer_name = 'selection302-peer'
        if service.registry.name_reserved(peer_name):
            service.owners.start(peer_name, agent_bin=str(runtime / 'pi-comms-native'), agent_args=launch.arguments)
            peer = service.registry.require(peer_name)
        else:
            peer = service.threads.fork(ForkSpec(peer_name, 'selection302', prompt=''), pi_bin=str(runtime / 'pi-comms-native'))
        receipt['private_peer'] = {'name': peer.name, 'process': FieldCodec.encode(peer.process_identity), 'session_file': peer.session_file}
        current = service.registry.require('selection302')
        env['TOAD_TEST_SELECTOR_MODEL'] = current.model
        command = [str(runtime / 'python'), str(Path(__file__).with_name('selector_warm_recording.py')),
            '--owner', 'Schrodinger304-merged-selector-sidebar', '--journey', 'selector_warm',
            '--private-root', str(service.root), '--peer-thread', peer_name,
            '--capture-state', '--scroll-travel', '--profile', '--profile-threads', 'gil',
            '--output', str(output / 'capture'), '--fit-window', '--width', '1280', '--height', '900',
            '--startup-wait', '1', '--history-wait-seconds', '35', '--max-duration', '240',
            '--finalize-seconds', '14', '--scroll-idle-seconds', '15', '--scroll-hold-seconds', '2',
            '--navigation-settle-seconds', '1', '--tail-seconds', '1', '--review-timing', 'deferred',
            '--', str(runtime / 'toad'), 'acp', shlex.join([str(runtime / 'python'), '-m', 'agent_comms.acp']),
            str(original.worktree), '--title', 'Agent Comms', '--session', 'selection302']
        (output / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        (output / 'source.json').write_text(json.dumps(receipt, indent=2) + '\n')
        with (output / 'runner.log').open('w') as log:
            owner.run(command, env, stdout=log, stderr=log, timeout=270)
    finally:
        cleanup = owner.cleanup()
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from runtime_fixture import stop_test_owners
        stop_test_owners(service.root)
        receipt['cleanup'] = cleanup
        receipt['private_owners_alive'] = {name: thread.process_alive for name, thread in service.registry.snapshot().threads.items()}
        with sqlite3.connect(service.root / 'coordination.sqlite3') as db:
            receipt['native_input_rows'] = db.execute('SELECT count(*) FROM native_runtime_input').fetchone()[0]
        receipt['settings_unchanged'] = all(digest(Path(path)) == value for path, value in settings.items())
        (output / 'source.json').write_text(json.dumps(receipt, indent=2) + '\n')
    assert not any(receipt['private_owners_alive'].values())
    assert receipt['native_input_rows'] == 0 and receipt['settings_unchanged']
    print(output / 'capture/receipt.json', flush=True)


if __name__ == '__main__':
    main()
