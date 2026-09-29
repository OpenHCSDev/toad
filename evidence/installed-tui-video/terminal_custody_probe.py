"""Bounded OS custody check, separate from the real installed UI acceptance.

Run with the paired installed Python and VIDEO_TERMINAL_PROBE_OUTPUT pointing
to a fresh named agent-scratch directory. AGENT_COMMS_ROOT selects an existing
private or archived Registration for the profiler's owner exclusion. No capture,
app state replacement or owner bus operations.
"""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import select
import signal
import subprocess
import sys
import time


def main():
    source = Path(__file__).resolve().parents[2] / 'tests/tools/record_installed_tui.py'
    spec = importlib.util.spec_from_file_location('recorder', source)
    recorder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = recorder
    spec.loader.exec_module(recorder)
    output = Path(os.environ['VIDEO_TERMINAL_PROBE_OUTPUT']).resolve()
    assert output.is_relative_to(Path.home() / '.cache/agent-scratch')
    output.mkdir(exist_ok=False)
    owner = recorder.ProcessOwner()
    result = {'recorder_source_sha256': recorder.digest(source), 'cases': {}}
    try:
        read_fd, write_fd = os.pipe()
        number = next(n for n in (secrets.randbelow(9000) + 100 for _ in range(100))
                      if not Path(f'/tmp/.X{n}-lock').exists()
                      and not Path(f'/tmp/.X11-unix/X{n}').exists())
        try:
            owner.start(['Xvfb', f':{number}', '-displayfd', str(write_fd),
                         '-screen', '0', '640x400x24', '-nolisten', 'tcp'],
                        pass_fds=(write_fd,), stderr=subprocess.DEVNULL)
        finally:
            os.close(write_fd)
        try:
            assert select.select([read_fd], [], [], 5)[0]
            assert os.read(read_fd, 32).decode().strip() == str(number)
        finally:
            os.close(read_fd)
        env = os.environ.copy()
        env['DISPLAY'] = f':{number}'
        result['display'] = env['DISPLAY']
        terminal = owner.start(['st', '-e', sys.executable, '-c', 'import time; time.sleep(30)'], env=env)
        program = recorder.terminal_program(owner, terminal.child.identity, time.monotonic() + 5)
        assert os.getsid(program.child.identity.pid) == program.child.identity.pid
        terminal.stop(signal.SIGKILL)
        program.stop()
        assert not program.child.identity.alive()
        result['cases']['abrupt_terminal_exit'] = 'separate program session cleaned'

        failed = owner.start(['st', '-e', '/usr/bin/sleep', '30'], env=env)
        published = []
        try:
            recorder.terminal_program(owner, failed.child.identity, time.monotonic() + .5,
                                      published.append)
            raise AssertionError('Wrong interpreter unexpectedly accepted')
        except RuntimeError:
            pass
        assert len(published) == 1
        result['cases']['runtime_verification_failure'] = 'custody acquired before failed verification'

        profile = output / 'profiler-handoff'
        profile.mkdir()
        env.update(TOAD_VIDEO_OUTPUT=str(profile), TOAD_VIDEO_PROFILE_RATE='10',
                   TOAD_VIDEO_PROFILE_DURATION='5')
        with (profile / 'log').open('w') as log:
            wrapper = owner.start([sys.executable, str(source), '--profile-launch',
                                   sys.executable, '-c', 'import time; time.sleep(30)'],
                                  env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 5
            while not (profile / 'profile-launch.json').exists() and time.monotonic() < deadline:
                assert wrapper.process.poll() is None
                time.sleep(.05)
            lease = json.loads((profile / 'profile-terminal.json').read_text())
            owner.transfer(lease['pid'], lease['start_ticks'])
            owner.transfer(lease['program']['pid'], lease['program']['start_ticks'])
            wrapper.stop(signal.SIGKILL)
        result['cases']['profiler_abrupt_exit'] = 'exact terminal and program leases recovered'
    finally:
        result['cleanup'] = owner.cleanup()
        result['still_live'] = [p.child.identity.pid for p in owner.children if p.child.identity.alive()]
        (output / 'acceptance.json').write_text(json.dumps(result, indent=2) + '\n')
    assert result['cleanup']['remaining_owned_pids'] == []
    assert result['cleanup']['errors'] == []
    assert result['still_live'] == []
    print(json.dumps(result['cases']))


if __name__ == '__main__':
    main()
