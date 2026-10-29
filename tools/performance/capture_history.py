"""Root-only, normal-user 25-second history/frame observer. AUTHOR MUST NOT RUN.

Example (fill current identity, approved runtime and reviewed meter hash):
  python capture_history.py start --pid PID --boot BOOT --start-ticks TICKS \
      --runtime /absolute/runtime --meter /reviewed/frame_meter.py --sha256 HASH \
      --output /home/ts/.cache/agent-scratch/OWNER/p903-UNIQUE --approved

Recovery (one distinct stop operation; never repeat an uncertain start):
  python capture_history.py cleanup --output SAME_DIRECTORY --approved

No screenshots, display ownership, GUI input, providers, services or heap walks.
A blocked target cannot promise remote restoration; retain cleanup.py and report it.
"""

import argparse
import ast
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from history_capture_remote import process_identity as identity, publish, read_meter_source


# Ordinary helper import performs no attachment. Controller and target share
# the bounded source reader and metadata publisher; only a copied request executes.


def validate_meter(path, digest):
    raw = read_meter_source(path, digest)
    tree = ast.parse(raw)
    declarations = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in ('install', 'trace_calls'):
        if name not in declarations or not {'max_records', 'max_bytes', 'metadata_only'} <= {
                argument.arg for argument in declarations[name].args.kwonlyargs}:
            raise ValueError('UNSUPPORTED_BOUNDED_TRACE')
    owners = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'BoundedCapture']
    if len(owners) != 1 or not any(isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == 'CONTRACT' for target in node.targets)
            and isinstance(node.value, ast.Constant) and node.value.value == 1 for node in owners[0].body):
        raise ValueError('UNSUPPORTED_BOUNDED_TRACE')
    return raw


def attach(pid, script):
    # A fresh helper bounds a stuck sys.remote_exec itself. Killing this helper
    # does NOT kill the frontend and does NOT prove its remote code did not run.
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), 'attach',
                             '--pid', str(pid), '--script', str(script)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=5, check=False)
    if result.returncode:
        raise RuntimeError('ATTACH_OUTCOME_UNCERTAIN')


def cleanup(directory):
    request = json.loads((directory / 'cleanup.json').read_text())
    if identity(request['identity']['pid']) != request['identity']:
        raise RuntimeError('Process birth changed: do not attach')
    attach(request['identity']['pid'], directory / 'cleanup.py')
    deadline = time.monotonic() + 2
    result_path = directory / 'cleanup-result.json'
    while time.monotonic() < deadline:
        if result_path.exists():
            result = json.loads(result_path.read_text())
            return result
        time.sleep(.25)
    return dict(status='CLEANUP_UNCONFIRMED', reason='target did not report restoration')


def start(args):
    directory = args.output.resolve()
    if not directory.is_relative_to(Path('/home/ts/.cache/agent-scratch')) or directory.exists():
        raise ValueError('Use a fresh, persistent owned scratch run directory')
    expected = dict(pid=args.pid, boot=args.boot, start_ticks=args.start_ticks)
    if identity(args.pid) != expected:
        raise RuntimeError('Process birth mismatch')
    runtime = args.runtime.resolve(strict=True)
    if runtime != args.runtime or not runtime.is_dir():
        raise ValueError('Runtime must be an explicit canonical directory')
    maps = Path(f'/proc/{args.pid}/maps').read_text()
    if str(runtime) + '/' not in maps:
        raise ValueError('Expected runtime not mapped by requested process')
    meter = args.meter.resolve(strict=True)
    validate_meter(meter, args.sha256)  # interface/hash failure BEFORE any attach
    if not hasattr(sys, 'remote_exec'):
        raise RuntimeError('UNSUPPORTED_BOUNDED_TRACE')
    remote = Path(__file__).with_name('history_capture_remote.py').read_bytes()
    # Charge both source copies, their actual path prefixes and bounded receipts.
    metadata_size = 2 * len(remote) + 2 * 8192 + 6 * 65536
    directory.mkdir(mode=0o700)
    request = dict(identity=expected, runtime=str(runtime), meter=str(meter),
                   meter_sha256=args.sha256, contract=1, token=uuid.uuid4().hex)
    for operation in ('start', 'cleanup'):
        script = directory / (operation + '.py')
        # sys.remote_exec supplies no __file__; each copy owns its adjacent request.
        prefix = f'__file__ = {str(script)!r}\n'.encode('utf-8')
        metadata_size += len(prefix)
        if metadata_size > 1 << 20:
            raise ValueError('Launcher metadata exceeds 1MiB reservation')
        request_path = directory / (operation + '.json')
        value = dict(request, operation=operation)
        if len(json.dumps(value).encode('utf-8')) > 8192:
            raise ValueError('Request exceeds reserved remote envelope')
        publish(request_path, value)
        script.write_bytes(prefix + remote)
        script.chmod(0o600)
    publish(directory / 'manifest.json', dict(identity=expected, runtime=str(runtime),
                                             meter_sha256=args.sha256, seconds=25,
                                             calls_max_bytes=12 << 20, frames_max_bytes=3 << 20,
                                             metadata_max_bytes=1 << 20, max_records=20000,
                                             status='PREPARED_NOT_ATTACHED'))
    began = time.monotonic()
    try:
        # Recheck birth immediately before the only start attempt.
        if identity(args.pid) != expected:
            raise RuntimeError('Process birth changed')
        attach(args.pid, directory / 'start.py')
        # Leave seven seconds for the one cleanup attempt and its receipt.
        deadline = began + 28
        while time.monotonic() < deadline:
            complete = directory / 'complete.json'
            if complete.exists():
                result = json.loads(complete.read_text())
                publish(directory / 'controller-result.json', result)
                return
            failure = directory / 'start-result.json'
            if failure.exists():
                raise RuntimeError('Remote setup failed; inspect bounded start result')
            time.sleep(.25)
        raise TimeoutError('Capture did not finish by controller deadline')
    except BaseException as error:
        try:
            result = cleanup(directory)  # a stop, NOT replay of the start input
        except BaseException as stop_error:
            result = dict(status='CLEANUP_UNCONFIRMED', error=type(stop_error).__name__[:96])
        publish(directory / 'controller-result.json', dict(status='INCONCLUSIVE',
                error=type(error).__name__[:96], cleanup=result,
                recovery_script=str(directory / 'cleanup.py')))
        raise


def interrupted(_signal, _frame):
    raise InterruptedError('Controller interrupted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('start', 'cleanup', 'attach'))
    parser.add_argument('--approved', action='store_true', help='root reviewed this exact source')
    parser.add_argument('--pid', type=int)
    parser.add_argument('--boot')
    parser.add_argument('--start-ticks', type=int)
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--meter', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--script', type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Normal-user observation only; never sudo this launcher')
    if args.operation == 'attach':
        sys.remote_exec(args.pid, str(args.script))
        return
    if not args.approved:
        parser.error('Root must review source and explicitly approve execution')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if args.operation == 'cleanup':
        print(json.dumps(cleanup(args.output.resolve()), separators=(',', ':')))
    else:
        if any(value is None for value in (args.pid, args.boot, args.start_ticks, args.runtime,
                                           args.meter, args.sha256, args.output)):
            parser.error('Start needs every explicit identity/runtime/meter/hash/output field')
        start(args)


if __name__ == '__main__':
    main()
