"""Actual installed login chooser / Pi PTY / credential-boundary cancellation.

Uses the existing isolated recorder and native hit-target helper. No provider
request, authentication submission, credential source or public owner restart.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sqlite3
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-bin', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review-existing', action='store_true')
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    recorder_path = Path(__file__).parent / 'tools/record_installed_tui.py'
    spec = importlib.util.spec_from_file_location('login_physical_recorder', recorder_path)
    recorder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = recorder
    spec.loader.exec_module(recorder)

    class ProviderLoginJourney(recorder.PhysicalJourney):
        scope = 'Installed provider chooser, first advertised method, native Pi PTY and Cancel before login submission'
        duration_seconds = 55

        @classmethod
        def script(cls, options):
            mark = recorder.marker_command()
            click = recorder.native_click_command
            return '\n'.join([
                mark + 'startup',
                click('phase-startup-state.pickle', target='widget', name='AgentInfo'),
                'sleep .5', mark + 'model-picker',
                click('phase-model-picker-state.pickle', target='widget', name='ConnectProvider'),
                'sleep .5', mark + 'provider-chooser',
                click('phase-provider-chooser-state.pickle', target='widget', name='ContextMenuItem', focused=True),
                'sleep 4', mark + 'native-handoff',
                click('phase-native-handoff-state.pickle', target='widget', name='Button#cancel'),
                'sleep 1', mark + 'cancelled', '',
            ])

    base = args.output.resolve()
    assert base.is_relative_to(Path.home() / '.cache/agent-scratch')
    candidate = args.candidate_bin.resolve(strict=True)
    assert Path(sys.prefix).resolve() == candidate.parent
    assert (candidate.parent / 'activation.json').is_file()
    if not args.review_existing:
        base.mkdir(parents=True, exist_ok=False)
        source = Path.home() / '.local/state/toad/toad.db'
        target = base / 'state/toad/toad.db'
        target.parent.mkdir(parents=True)
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
            with sqlite3.connect(target) as copied:
                original.backup(copied)
        os.environ['XDG_STATE_HOME'] = str(base / 'state')
        # Login's separate Pi UI uses an empty, owned account directory. It
        # cannot read/write the user's native credentials or complete auth.
        agent_dir = base / 'login-agent'
        agent_dir.mkdir(mode=0o700)
        os.environ['PI_CODING_AGENT_DIR'] = str(agent_dir)
        activation = json.loads((candidate.parent / 'activation.json').read_text())
        native = Path(activation['native_package'])
        binary = json.loads((native / 'package.json').read_text())['bin']['pi']
        os.environ['AGENT_COMMS_AGENT_BIN'] = str(native / binary)
        for key in tuple(os.environ):
            if key.endswith('_API_KEY'):
                os.environ.pop(key)
        for key in ('NO_COLOR', 'PYTHONPATH', 'AGENT_COMMS_THREAD', 'AGENT_COMMS_MANAGED',
                    'PI_AGENT_ID', 'PI_PARENT_ID', 'PI_TASK', 'PI_WORKTREE', 'PI_PROMPT'):
            os.environ.pop(key, None)
        os.environ['AGENT_COMMS_RUNTIME_ROOT'] = str(candidate)
        os.environ['AGENT_COMMS_ACP_LAUNCHER'] = str(candidate / 'agent-comms-acp')
        from agent_comms.comms import wire
        from agent_comms.field_codec import FieldCodec
        def original_source():
            thread = wire().registry.require('nra-architecture')
            path = Path(thread.session_file)
            return {'owner': FieldCodec.encode(thread.process_identity),
                    'active_turn': FieldCodec.encode(thread.active_turn),
                    'source': str(path), 'bytes': path.stat().st_size,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        (base / 'original-before.json').write_text(json.dumps(original_source(), indent=2)+'\n')
        actions = base / 'actions.xdo'
        actions.write_text(ProviderLoginJourney.script(None))
        sys.argv = [str(recorder_path), '--output', str(base / 'capture'), '--owner', 'Einstein-login243',
                    '--capture-target', 'existing_thread', '--journey', ProviderLoginJourney.declared_name,
                    '--capture-state', '--actions', str(actions), '--review-timing', 'deferred', '--fps', '30',
                    '--width', '1280', '--height', '900', '--fit-window', '--startup-wait', '12',
                    '--max-duration', '55', '--tail-seconds', '2', '--',
                    '/home/ts/bin/toad-comms', 'nra-architecture']
        try:
            recorder.main()
        finally:
            (base / 'original-after.json').write_text(json.dumps(original_source(), indent=2)+'\n')
    def phase(label):
        return pickle.loads((base / f'capture/phase-{label}-state.pickle').read_bytes())
    receipt = json.loads((base / 'capture/receipt.json').read_text())
    assert receipt['completed'] and receipt['capture_completed']
    assert phase('provider-chooser')['metadata']['screen']['class'] == 'ContextMenu'
    assert phase('native-handoff')['metadata']['screen']['class'] == 'ActionModal'
    assert phase('cancelled')['metadata']['screen']['class'] != 'ActionModal'
    assert phase('cancelled')['metadata']['current_mode'] == phase('startup')['metadata']['current_mode']
    assert (base/'original-before.json').read_bytes() == (base/'original-after.json').read_bytes()
    auth = base / 'login-agent/auth.json'
    assert json.loads(auth.read_text()) == {}, 'Native may initialize an empty store, but not create credentials'
    (base / 'scoped-native-review.json').write_text(json.dumps({
        'actual_provider_choice_click': True, 'actual_login_modal': True, 'actual_cancel_click': True,
        'original_source_and_owner_unchanged': True, 'credential_account_changes': 0,
        'provider_requests': 0, 'native_prompts': 0,
        'physical_native_login_prompt_review_required': True,
        'scope': ProviderLoginJourney.scope,
    }, indent=2)+'\n')


if __name__ == '__main__':
    main()
