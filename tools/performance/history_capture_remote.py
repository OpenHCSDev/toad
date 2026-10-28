"""Root's remote start/cleanup script; copied beside an immutable JSON request.

Executed by normal-user sys.remote_exec, never by an author or from a renderer.
No UI input, provider traffic, snapshot, product repr or heap traversal.
"""

import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


STATUS_LIMIT = 65536
REGISTRY = '_toad_history_captures'


def process_identity(pid=None):
    pid = os.getpid() if pid is None else pid
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return dict(pid=pid, boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                start_ticks=int(stat[19]))


def publish(path, value):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(data) > STATUS_LIMIT:
        raise ValueError('Manifest exceeds reserved metadata bound')
    partial = path.with_name(path.name + '.partial')
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as file:
        file.write(data)
    os.rename(partial, path)


def require_identity(request):
    if process_identity() != request['identity']:
        raise RuntimeError('Capture process birth mismatch')
    runtime = Path(request['runtime']).resolve(strict=True)
    if runtime != Path(request['runtime']):
        raise ValueError('Runtime must be an explicit canonical directory')
    return runtime


def require_modules(runtime):
    """Check loaded package provenance, not heap objects or product values.

    A module filename establishes location, NOT a hash of already-loaded code.
    The manifest makes that limitation explicit. No product import is needed.
    """
    checked = 0
    for name, module in tuple(sys.modules.items()):
        if name.split('.', 1)[0] not in ('toad', 'textual', 'agent_comms'):
            continue
        location = getattr(module, '__file__', None)  # foreign Python module boundary
        if location is None or not Path(location).resolve(strict=True).is_relative_to(runtime):
            raise RuntimeError('Loaded package is outside approved runtime')
        checked += 1
    if not checked or 'toad.app' not in sys.modules:
        raise RuntimeError('No loaded Toad runtime to observe')
    return checked


class RemoteCaptureRun:
    """The one token's returned handles and group timer, never product objects."""

    def __init__(self, token, module, registry):
        self.token, self.module, self.registry = token, module, registry
        self.handles = []
        self.timer = None
        self.status = None

    def finish(self, reason, status_path):
        if self.status is None:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            results = []
            for finish in reversed(self.handles):
                try:
                    results.append(finish(reason))
                except BaseException as error:
                    results.append(dict(cleanup='failed', error=type(error).__name__[:96]))
            self.handles.clear()
            self.registry.pop(self.token, None)
            sys.modules.pop(self.module, None)
            successful = reason != 'setup-error' and all(
                result.get('cleanup') == 'restored' and not result.get('error')
                and not result.get('cap_exhausted') for result in results)
            self.status = dict(status='FINISHED' if successful else 'INCONCLUSIVE',
                               reason=reason, token=self.token, captures=results,
                               attribution='INCONCLUSIVE_UNTIL_PAGE_CORRELATION',
                               pixels_observed=False)
        publish(status_path, self.status)


def finish_token(request, status_path):
    require_identity(request)
    registry = getattr(sys, REGISTRY, {})
    entry = registry.get(request['token'])
    if entry is None:
        completed = status_path.parent / 'complete.json'
        if completed.exists():
            result = json.loads(completed.read_text())
            if result.get('token') == request['token']:
                publish(status_path, result)
                return
        # Missing token is NOT evidence that an uncertain attach did nothing.
        publish(status_path, dict(status='CLEANUP_UNCONFIRMED', reason='token-not-present'))
        return
    entry.finish('controller-cleanup', status_path)


def start(request, directory):
    runtime = require_identity(request)
    loop = asyncio.get_running_loop()  # never set up in a synchronous child
    checked = require_modules(runtime)
    meter_path = Path(request['meter']).resolve(strict=True)
    if hashlib.sha256(meter_path.read_bytes()).hexdigest() != request['meter_sha256']:
        raise RuntimeError('Approved meter changed')
    module_name = '_toad_history_meter_' + request['token']
    registry = getattr(sys, REGISTRY, None)
    if registry is None:
        registry = {}
        setattr(sys, REGISTRY, registry)
    if registry:  # no parallel capture and no overwrite of uncertain retained handles
        raise RuntimeError('An existing history capture still owns handles')
    spec = importlib.util.spec_from_file_location(module_name, meter_path)
    meter = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = meter
    entry = RemoteCaptureRun(request['token'], module_name, registry)
    registry[request['token']] = entry
    handles = entry.handles
    try:
        spec.loader.exec_module(meter)
        if meter.BoundedCapture.CONTRACT != request['contract']:
            raise RuntimeError('UNSUPPORTED_BOUNDED_TRACE')
        # Validate ALL actual methods/metadata adapters before either collector patches.
        targets = tuple(meter.CallMetadata.targets)
        for target in targets:
            meter.MethodTarget(target)
        checked = require_modules(runtime)  # include any modules target resolution loaded
        handles.append(meter.install(expected_pid=request['identity']['pid'], seconds=25,
                                     output=str(directory / 'frames.json'), max_records=20000,
                                     max_bytes=3 << 20, metadata_only=True))
        handles.append(meter.trace_calls(expected_pid=request['identity']['pid'], seconds=25,
                                         output=str(directory / 'calls.json'), targets=targets,
                                         max_records=20000, max_bytes=12 << 20, metadata_only=True))

        entry.timer = loop.call_later(25, entry.finish, 'duration', directory / 'complete.json')
        publish(directory / 'entered.json', dict(status='ENTERED', identity=process_identity(),
                                                modules_checked=checked, runtime=str(runtime),
                                                meter_sha256=request['meter_sha256'],
                                                provenance='loaded module locations, not loaded-code hashes',
                                                started_ns=time.monotonic_ns(), seconds=25,
                                                source_match='not-required; infer only from observed page spans'))
    except BaseException:
        entry.finish('setup-error', directory / 'complete.json')
        raise


def execute():
    script = Path(__file__).resolve()
    request_path = script.with_suffix('.json')
    if request_path.stat().st_size > 8192:
        raise ValueError('Oversize capture request')
    request = json.loads(request_path.read_text())
    status = script.parent / (script.stem + '-result.json')
    try:
        if request['operation'] == 'start':
            start(request, script.parent)
        elif request['operation'] == 'cleanup':
            finish_token(request, status)
        else:
            raise ValueError('Unsupported remote operation')
    except BaseException as error:
        publish(status, dict(status='FAILED_CLEANUP_UNCONFIRMED', error=type(error).__name__[:96]))


# Only the copied execution scripts have their explicit request beside them.
# Ordinary import by the controller has no request and performs no remote work.
if Path(__file__).with_suffix('.json').is_file():
    execute()
