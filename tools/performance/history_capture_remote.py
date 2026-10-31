"""Root's remote start/cleanup script; copied beside an immutable typed request.

Executed by normal-user sys.remote_exec, never by an author or from a renderer.
No UI input, provider traffic, snapshot, product repr or heap traversal.
"""

from abc import abstractmethod
import asyncio
from dataclasses import dataclass, fields
import hashlib
import importlib.machinery
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import FieldCodec


STATUS_LIMIT = 65536
REGISTRY = '_toad_history_captures'
METER_SOURCE_LIMIT = 256 << 10


@dataclass(frozen=True)
class CaptureSpec:
    """One immutable selection for both collectors and their enclosing lifetime.

    Scalar shape/positivity is checked at construction. BoundedCapture remains
    the owner of physical admission ceilings and exact encoded byte accounting.
    """

    seconds: float = 25.0
    frames_max_records: int = 20000
    calls_max_records: int = 20000
    frames_max_bytes: int = 3 << 20
    calls_max_bytes: int = 12 << 20

    attach_timeout: ClassVar[float] = 5.0
    completion_grace: ClassVar[float] = 3.0
    cleanup_receipt_timeout: ClassVar[float] = 2.0
    poll_interval: ClassVar[float] = .25
    error_bytes: ClassVar[int] = 2048
    metadata_max_bytes: ClassVar[int] = 1 << 20

    def __post_init__(self):
        # This is the foreign CLI/JSON scalar boundary, not product dispatch.
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not item.type or not math.isfinite(value) or value <= 0:
                raise ValueError(f'Invalid positive finite capture scalar: {item.name}')

    @property
    def observation_budget(self):
        return self.attach_timeout + self.seconds + self.completion_grace

    @property
    def cleanup_budget(self):
        return self.attach_timeout + self.cleanup_receipt_timeout

    @property
    def controller_budget(self):
        return self.observation_budget + self.cleanup_budget


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    boot: str
    start_ticks: int


class CaptureOperation(DeclaredFamily, affix='Capture'):
    """Each copied request declares which operation its script may execute."""

    @abstractmethod
    def execute(self, request: 'CaptureRequest', directory: Path): ...


@dataclass(frozen=True)
class CaptureRequest:
    identity: ProcessIdentity
    runtime: Path
    meter: Path
    meter_sha256: str
    contract: int
    token: str
    capture: CaptureSpec
    operation: CaptureOperation


def error_metadata(error):
    """Bound exception diagnostics; never serialize a product object or traceback."""
    detail = str(error).encode('utf-8', errors='replace')[:CaptureSpec.error_bytes]
    return dict(error=type(error).__name__[:96], detail=detail.decode('utf-8', errors='ignore'))


def read_meter_source(path, digest):
    """The approved source buffer, with one bounded read and one identity check."""
    with path.open('rb') as source:
        raw = source.read(METER_SOURCE_LIMIT + 1)
    if len(raw) > METER_SOURCE_LIMIT:
        raise ValueError('Oversize meter source')
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Approved meter hash mismatch')
    return raw


def process_identity(pid=None):
    pid = os.getpid() if pid is None else pid
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return ProcessIdentity(pid=pid, boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                           start_ticks=int(stat[19]))


def publish(path, value):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(data) > STATUS_LIMIT:
        raise ValueError('Manifest exceeds reserved metadata bound')
    partial = path.with_name(path.name + '.partial')
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    # Only successful exclusive creation grants this attempt cleanup ownership.
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
        os.rename(partial, path)
    except BaseException as error:
        try:
            partial.unlink(missing_ok=True)
        except BaseException as cleanup_error:
            raise error from cleanup_error
        raise


def require_identity(request):
    if process_identity() != request.identity:
        raise RuntimeError('Capture process birth mismatch')
    runtime = request.runtime.resolve(strict=True)
    if runtime != request.runtime:
        raise ValueError('Runtime must be an explicit canonical directory')
    return runtime


def require_modules(runtime):
    """Read the foreign ModuleSpec's origin or every namespace search location.

    Locations establish provenance, NOT hashes of already-loaded code. No
    package is imported or excused by its spelling at this boundary.
    """
    checked = 0
    for name, module in tuple(sys.modules.items()):
        if name.split('.', 1)[0] not in ('toad', 'textual', 'agent_comms'):
            continue
        spec = getattr(module, '__spec__', None)  # foreign Python module boundary
        if not isinstance(spec, importlib.machinery.ModuleSpec):
            raise RuntimeError(f'Loaded package has no ModuleSpec: {name[:160]}')
        locations = ((spec.origin,) if spec.has_location else
                     tuple(spec.submodule_search_locations or ()))
        if not locations:
            raise RuntimeError(f'Loaded package has no owned locations: {name[:160]}')
        for location in locations:
            resolved = Path(location).resolve(strict=True)
            if not resolved.is_relative_to(runtime):
                raise RuntimeError(f'Loaded package outside approved runtime: {name[:160]} {str(resolved)[:384]}')
        checked += 1
    if not checked or 'toad.app' not in sys.modules:
        raise RuntimeError('No loaded Toad runtime to observe')
    return checked


class RemoteCaptureRun:
    """The one token's returned handles and group timer, never product objects."""

    def __init__(self, token, module, registry, directory):
        self.token, self.module, self.registry = token, module, registry
        self.completion_path = self.completion_file(directory)
        self.handles = []
        self.timer = None
        self.status = None

    @staticmethod
    def completion_file(directory):
        return directory / 'complete.json'

    @classmethod
    def read_completion(cls, directory, token):
        """Only this run's bounded canonical completion can prove it finished."""
        path = cls.completion_file(directory)
        if not path.exists():
            return None
        with path.open('rb') as source:
            raw = source.read(STATUS_LIMIT + 1)
        if len(raw) > STATUS_LIMIT:
            raise ValueError('Oversize canonical completion')
        result = json.loads(raw)
        return result if result.get('token') == token else None

    def finish(self, reason, **diagnostic):
        if self.status is None:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            results = []
            for finish in reversed(self.handles):
                try:
                    results.append(finish(reason))
                except BaseException as error:
                    results.append(dict(cleanup='failed', **error_metadata(error)))
            self.handles.clear()
            successful = reason != 'setup-error' and all(
                result.get('cleanup') == 'restored' and not result.get('error')
                and not result.get('cap_exhausted') for result in results)
            self.status = dict(status='FINISHED' if successful else 'INCONCLUSIVE',
                               reason=reason, token=self.token, captures=results,
                               attribution='INCONCLUSIVE_UNTIL_PAGE_CORRELATION',
                               pixels_observed=False, **diagnostic)
        # Keep the completed owner reachable if publication fails. A later
        # distinct cleanup may publish its original status without restoring twice.
        publish(self.completion_path, self.status)
        self.registry.pop(self.token, None)
        sys.modules.pop(self.module, None)
        return self.status


@dataclass(frozen=True)
class CleanupCapture(CaptureOperation):
    def execute(self, request, directory):
        require_identity(request)
        registry = getattr(sys, REGISTRY, {})
        entry = registry.get(request.token)
        if entry is not None:
            return entry.finish('controller-cleanup')
        if (result := RemoteCaptureRun.read_completion(directory, request.token)) is not None:
            return result
        # Missing token is NOT evidence that an uncertain attach did nothing.
        return dict(status='CLEANUP_UNCONFIRMED', reason='token-not-present')


@dataclass(frozen=True)
class StartCapture(CaptureOperation):
    def execute(self, request, directory):
        runtime = require_identity(request)
        loop = asyncio.get_running_loop()  # never set up in a synchronous child
        checked = require_modules(runtime)
        meter_path = request.meter.resolve(strict=True)
        source = read_meter_source(meter_path, request.meter_sha256)
        module_name = '_toad_history_meter_' + request.token
        registry = getattr(sys, REGISTRY, None)
        if registry is None:
            registry = {}
            setattr(sys, REGISTRY, registry)
        if registry:  # no parallel capture and no overwrite of uncertain retained handles
            raise RuntimeError('An existing history capture still owns handles')
        spec = importlib.util.spec_from_file_location(module_name, meter_path)
        meter = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = meter
        entry = RemoteCaptureRun(request.token, module_name, registry, directory)
        registry[request.token] = entry
        handles = entry.handles
        capture = request.capture
        try:
            # Execute precisely the hash-verified bytes. Never reopen this mutable
            # path through the loader or accept its cached bytecode instead.
            exec(compile(source, str(meter_path), 'exec', dont_inherit=True), vars(meter))
            if meter.BoundedCapture.CONTRACT != request.contract:
                raise RuntimeError('UNSUPPORTED_BOUNDED_TRACE')
            # Validate ALL actual methods/metadata adapters before either collector patches.
            targets = tuple(meter.CallMetadata.targets)
            meter._metadata_boundary()  # resolve all nominal metadata declarations before patching
            for target in targets:
                meter.MethodTarget(target)
            checked = require_modules(runtime)  # include any modules target resolution loaded
            handles.append(meter.install(expected_pid=request.identity.pid, seconds=capture.seconds,
                                         output=str(directory / 'frames.json'), max_records=capture.frames_max_records,
                                         max_bytes=capture.frames_max_bytes, metadata_only=True))
            handles.append(meter.trace_calls(expected_pid=request.identity.pid, seconds=capture.seconds,
                                             output=str(directory / 'calls.json'), targets=targets,
                                             max_records=capture.calls_max_records,
                                             max_bytes=capture.calls_max_bytes, metadata_only=True))

            entry.timer = loop.call_later(capture.seconds, entry.finish, 'duration')
            publish(directory / 'entered.json', dict(status='ENTERED', identity=FieldCodec.encode(process_identity()),
                                                    modules_checked=checked, runtime=str(runtime),
                                                    meter_sha256=request.meter_sha256,
                                                    provenance='loaded module locations, not loaded-code hashes',
                                                    started_ns=time.monotonic_ns(), capture=FieldCodec.encode(capture),
                                                    source_match='not-required; infer only from observed page spans'))
        except BaseException as error:
            return entry.finish('setup-error', **error_metadata(error))


def execute():
    script = Path(__file__).resolve()
    status = script.parent / (script.stem + '-result.json')
    try:
        request_path = script.with_suffix('.json')
        if request_path.stat().st_size > 8192:
            raise ValueError('Oversize capture request')
        request = FieldCodec.decode(CaptureRequest, json.loads(request_path.read_text()))
        result = request.operation.execute(request, script.parent)
    except BaseException as error:
        result = dict(status='FAILED_CLEANUP_UNCONFIRMED', **error_metadata(error))
    if result is not None:
        publish(status, result)


# Only the copied execution scripts have their explicit request beside them.
# Ordinary import by the controller has no request and performs no remote work.
if Path(__file__).with_suffix('.json').is_file():
    execute()
