"""Root-only, normal-user bounded history/frame observer. AUTHOR MUST NOT RUN.

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
from dataclasses import fields, replace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from agent_comms.field_codec import FieldCodec
from history_capture_remote import (
    CaptureOperation, CaptureRequest, CaptureSpec, ProcessIdentity, RemoteCaptureRun, StartCapture,
    error_metadata, process_identity as identity, publish, read_meter_source,
)


# Ordinary helper import performs no attachment. Controller and target share
# the typed request, bounded source reader and publisher; only a copied request executes.


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


def attach(pid, script, capture):
    # A fresh helper bounds a stuck sys.remote_exec itself. Killing this helper
    # does NOT kill the frontend and does NOT prove its remote code did not run.
    # The helper emits bounded exception metadata. A file avoids an unbounded
    # parent-side PIPE buffer; only the bounded diagnostic enters our receipt.
    with tempfile.TemporaryFile(dir=script.parent) as stderr:
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), 'attach',
                                     '--pid', str(pid), '--script', str(script)],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=stderr, timeout=capture.attach_timeout, check=False)
        except (subprocess.TimeoutExpired, OSError) as error:
            stderr.seek(0)
            detail = stderr.read(capture.error_bytes).decode('utf-8', errors='replace')
            raise RuntimeError(f'ATTACH_OUTCOME_UNCERTAIN: {detail} {type(error).__name__}: {str(error)[:capture.error_bytes]}') from error
        if result.returncode:
            stderr.seek(0)
            detail = stderr.read(capture.error_bytes).decode('utf-8', errors='replace')
            raise RuntimeError(f'ATTACH_OUTCOME_UNCERTAIN: helper exit {result.returncode}: {detail}')


def cleanup(directory):
    request = FieldCodec.decode(CaptureRequest, json.loads((directory / 'cleanup.json').read_text()))
    if (result := RemoteCaptureRun.read_completion(directory, request.token)) is not None:
        return result
    if identity(request.identity.pid) != request.identity:
        raise RuntimeError('Process birth changed: do not attach')
    capture = request.capture
    attach(request.identity.pid, directory / 'cleanup.py', capture)
    deadline = time.monotonic() + capture.cleanup_receipt_timeout
    while time.monotonic() < deadline:
        if (result := RemoteCaptureRun.read_completion(directory, request.token)) is not None:
            return result
        time.sleep(capture.poll_interval)
    return dict(status='CLEANUP_UNCONFIRMED', reason='target did not publish matching canonical completion')


def start(args):
    capture = FieldCodec.decode(CaptureSpec, {item.name: vars(args)[item.name] for item in fields(CaptureSpec)})
    directory = args.output.resolve()
    if not directory.is_relative_to(Path('/home/ts/.cache/agent-scratch')) or directory.exists():
        raise ValueError('Use a fresh, persistent owned scratch run directory')
    expected = ProcessIdentity(pid=args.pid, boot=args.boot, start_ticks=args.start_ticks)
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
    request = CaptureRequest(identity=expected, runtime=runtime, meter=meter,
                             meter_sha256=args.sha256, contract=1, token=uuid.uuid4().hex,
                             capture=capture, operation=StartCapture())
    for operation in CaptureOperation.members_with(CaptureOperation):
        script = directory / (operation.declared_name + '.py')
        # sys.remote_exec supplies no __file__; each copy owns its adjacent request.
        prefix = f'__file__ = {str(script)!r}\n'.encode('utf-8')
        metadata_size += len(prefix)
        if metadata_size > capture.metadata_max_bytes:
            raise ValueError('Launcher metadata exceeds reservation')
        request_path = script.with_suffix('.json')
        value = FieldCodec.encode(replace(request, operation=operation()))
        if len(json.dumps(value).encode('utf-8')) > 8192:
            raise ValueError('Request exceeds reserved remote envelope')
        publish(request_path, value)
        script.write_bytes(prefix + remote)
        script.chmod(0o600)
    publish(directory / 'manifest.json', dict(identity=FieldCodec.encode(expected), runtime=str(runtime),
                                             meter_sha256=args.sha256, capture=FieldCodec.encode(capture),
                                             metadata_max_bytes=capture.metadata_max_bytes,
                                             controller_budget=capture.controller_budget,
                                             status='PREPARED_NOT_ATTACHED'))
    began = time.monotonic()
    try:
        # Recheck birth immediately before the only start attempt.
        if identity(args.pid) != expected:
            raise RuntimeError('Process birth changed')
        attach(args.pid, directory / 'start.py', capture)
        deadline = began + capture.observation_budget
        while time.monotonic() < deadline:
            if (result := RemoteCaptureRun.read_completion(directory, request.token)) is not None:
                publish(directory / 'controller-result.json', result)
                return
            failure = directory / 'start-result.json'
            if failure.exists():
                raise RuntimeError('Remote setup failed: ' + failure.read_text()[:capture.error_bytes])
            time.sleep(capture.poll_interval)
        raise TimeoutError('Capture did not finish by controller deadline')
    except BaseException as error:
        try:
            result = cleanup(directory)  # a stop, NOT replay of the start input
        except BaseException as stop_error:
            result = dict(status='CLEANUP_UNCONFIRMED', **error_metadata(stop_error))
        publish(directory / 'controller-result.json', dict(status='INCONCLUSIVE',
                **error_metadata(error), cleanup=result, recovery_script=str(directory / 'cleanup.py')))
        raise


def interrupted(_signal, _frame):
    raise InterruptedError('Controller interrupted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=(*(member.declared_name for member in
                        CaptureOperation.members_with(CaptureOperation)), 'attach'))
    parser.add_argument('--approved', action='store_true', help='root reviewed this exact source')
    parser.add_argument('--pid', type=int)
    parser.add_argument('--boot')
    parser.add_argument('--start-ticks', type=int)
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--meter', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--script', type=Path)
    for item in fields(CaptureSpec):
        parser.add_argument('--' + item.name.replace('_', '-'), type=item.type, default=item.default)
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Normal-user observation only; never sudo this launcher')
    if args.operation == 'attach':
        try:
            sys.remote_exec(args.pid, str(args.script))
        except BaseException as error:
            sys.stderr.write(json.dumps(error_metadata(error), ensure_ascii=False))
            raise SystemExit(1) from None
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
