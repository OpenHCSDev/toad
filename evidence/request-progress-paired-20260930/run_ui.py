"""Run the existing installed fork journey once on a frozen matched pair."""
import argparse
import asyncio
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import sys
import time


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tests', required=True, type=Path)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    stage = args.stage.resolve()
    base = args.output.resolve()
    assert base.is_relative_to(Path('/home/ts/wt'))
    assert Path(sys.prefix) == stage
    activation = json.loads((stage / 'activation.json').read_text())
    import toad
    import agent_comms
    assert Path(toad.__file__).is_relative_to(stage)
    assert Path(agent_comms.__file__).is_relative_to(stage)
    for package, pin in activation['pins'].items():
        provenance = json.loads(metadata.distribution(package).read_text('direct_url.json'))
        assert provenance['vcs_info']['commit_id'] == pin
    assert metadata.version('agent-client-protocol') == '0.12.1'
    tests = args.tests.resolve()
    sys.path.insert(0, str(tests))
    for key in ('PYTHONPATH', 'AGENT_COMMS_ROOT', 'AGENT_COMMS_RUNTIME_ROOT',
                'AGENT_COMMS_ACP_LAUNCHER', 'AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID',
                'AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE', 'AGENT_COMMS_THREAD',
                'AGENT_COMMS_MANAGED', 'PI_AGENT_ID', 'PI_PARENT_ID', 'PI_TASK',
                'PI_WORKTREE', 'PI_PROMPT', 'FORK_NATIVE_TASK', 'FORK_DIALOG_EVIDENCE'):
        os.environ.pop(key, None)
    base.mkdir(mode=0o700, exist_ok=False)
    evidence = base / 'proof'
    evidence.mkdir(mode=0o700)
    os.environ.update(
        TMPDIR=str(base), L0A_EVIDENCE=str(evidence),
        AC_NATIVE_COPIED_PACKAGE=activation['native_package'],
        PATH=str(stage / 'bin') + os.pathsep + os.environ['PATH'],
        PYTHONPATH=str(tests), TOAD_TEST_ATTEMPT='Einstein-g454e-u01',
        TOAD_TEST_SOURCE_HEAD=activation['pins']['batrachian-toad'],
    )
    from first_fork_native_installed_pilot import main, InstalledApp, acceptance
    started = time.monotonic()
    (evidence / 'preflight.json').write_text(json.dumps({
        'stage': str(stage), 'activation': activation,
        'toad': toad.__file__, 'core': agent_comms.__file__,
        'existing_journey': 'first_fork_native_installed_pilot.default_acceptance',
        'fixture': str(base / 'fixture'), 'tests': str(tests),
        'ui': 'Actual installed Toad, Pilot clicks and committed compositor/SVG',
        'physical_st_xvfb_gate': False, 'controlled_posts_budget': 2,
        'production_source_pythonpath': False, 'public_inputs': 0,
    }, indent=2) + '\n')
    code = 0
    try:
        asyncio.run(asyncio.wait_for(main(
            app_type=InstalledApp, acceptance=acceptance,
            provider_request_budget=2, fixture_stage=base / 'fixture'), 105))
    except BaseException:
        code = 1
        raise
    finally:
        (evidence / 'terminal-receipt.json').write_text(json.dumps({
            'exit_code': code, 'elapsed_seconds': time.monotonic() - started,
            'paid_calls': 0, 'public_mutations': 0, 'manual_replays': 0,
            'fixture_attempts': 1,
        }, indent=2) + '\n')


if __name__ == '__main__':
    run()
