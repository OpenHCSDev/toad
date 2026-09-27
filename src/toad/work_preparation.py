"""Shared, bounded worker work: identity, execution and reuse are separate policies."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Hashable, Mapping
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
import pickle
from sys import getsizeof
from typing import TYPE_CHECKING, Generic, TypeVar, cast

from toad.render_backend import Renderer

if TYPE_CHECKING:
    from toad.render_tasks import RenderTask

ResultT = TypeVar("ResultT")


class WorkLane(Enum):
    MODEL = "model"
    RENDER = "render"


class PreparationScope:
    """A snapshot lifetime token; never holds its widget or application owner."""

    def __init__(self) -> None:
        self.closed = False


@dataclass(frozen=True)
class WorkKey:
    kind: type
    revision: Hashable
    scope: PreparationScope | None = None


class PreparedValue(ABC, Generic[ResultT]):
    """Declaration-selected retained representation, delivered only by a worker."""

    __slots__ = ()

    size: int

    @abstractmethod
    def materialize(self) -> ResultT:
        """Return independent mutable data to one consumer."""


@dataclass(frozen=True, slots=True)
class CopiedValue(PreparedValue[ResultT]):
    value: ResultT
    size: int

    def materialize(self) -> ResultT:
        return deepcopy(self.value)


@dataclass(frozen=True, slots=True)
class SerializedValue(PreparedValue[ResultT]):
    payload: bytes

    @property
    def size(self) -> int:
        return getsizeof(self.payload) + getsizeof(self)

    def materialize(self) -> ResultT:
        # Only bytes encoded from this runtime's own prepared results enter here.
        return pickle.loads(self.payload)


def serialize_result(result: ResultT) -> SerializedValue[ResultT]:
    payload = pickle.dumps(result, protocol=5)
    return SerializedValue(payload)


class PreparationWork(ABC, Generic[ResultT]):
    """Nominal operation; the runtime does not switch on concrete work types."""

    retain_result = False

    def result_size(self, result: ResultT) -> int:
        return retained_bytes(result)

    def store_result(self, result: ResultT) -> PreparedValue[ResultT]:
        return CopiedValue(result, self.result_size(result) if self.retain_result else 0)

    @property
    @abstractmethod
    def lane(self) -> WorkLane:
        """Independent admission for models and potentially slow rendering."""

    @abstractmethod
    async def identity(self, runtime: PreparationRuntime) -> WorkKey:
        """Describe all source revision and presentation inputs to this result."""

    @abstractmethod
    async def execute(self, runtime: PreparationRuntime) -> ResultT:
        """Run through the declared worker execution policy."""


class ReusableWork(PreparationWork[ResultT]):
    """Mixin for results whose declared identity fully describes their inputs."""

    retain_result = True


class SerializedWork(ReusableWork[ResultT]):
    """Opt in when result data already has a supported process-transfer contract."""

    def store_result(self, result: ResultT) -> PreparedValue[ResultT]:
        return serialize_result(result)


class ContentAddressedWork(PreparationWork[ResultT]):
    @property
    @abstractmethod
    def inputs(self) -> object:
        """Data-only inputs; no widgets, services or mutable presentation state."""

    async def identity(self, runtime: PreparationRuntime) -> WorkKey:
        digest = await runtime.run_thread(lambda: sha256(pickle.dumps(self.inputs, protocol=5)).digest())
        return WorkKey(type(self), digest)


class ScopedWork(PreparationWork[ResultT]):
    @property
    @abstractmethod
    def work_key(self) -> WorkKey:
        """An owner-declared snapshot key, without retaining that owner."""

    async def identity(self, runtime: PreparationRuntime) -> WorkKey:
        return self.work_key


class ThreadWork(PreparationWork[ResultT]):
    lane = WorkLane.MODEL

    @abstractmethod
    def prepare(self) -> ResultT:
        """Prepare captured data on a worker thread."""

    async def execute(self, runtime: PreparationRuntime) -> ResultT:
        return await runtime.run_thread(self.prepare)


class RendererWork(PreparationWork[ResultT]):
    lane = WorkLane.RENDER

    @property
    @abstractmethod
    def render_task(self) -> RenderTask[ResultT]:
        """A task admitted by the existing local/persistent renderer."""

    async def execute(self, runtime: PreparationRuntime) -> ResultT:
        return await runtime.renderer.submit(self.render_task)


@dataclass(frozen=True)
class RenderPreparation(ContentAddressedWork[ResultT], RendererWork[ResultT]):
    task: RenderTask[ResultT]

    async def identity(self, runtime: PreparationRuntime) -> WorkKey:
        # Tasks such as path-aware Markdown read external state not represented
        # by their text. Their declaration opts out of both retention and sharing.
        if not self.task.reusable_result:
            return WorkKey(type(self), object())
        return await super().identity(runtime)

    @property
    def inputs(self) -> object:
        return self.task

    @property
    def render_task(self) -> RenderTask[ResultT]:
        return self.task

    @property
    def retain_result(self) -> bool:
        return self.task.reusable_result

    def store_result(self, result: ResultT) -> PreparedValue[ResultT]:
        return serialize_result(result) if self.retain_result else super().store_result(result)


def retained_bytes(value: object) -> int:
    """Bound retained model graphs, including nested tool inputs, off-loop."""
    pending = [value]
    seen: set[int] = set()
    total = 0
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        total += getsizeof(item)
        if is_dataclass(item) and not isinstance(item, type):
            pending.extend(getattr(item, field.name) for field in fields(item))
        elif isinstance(item, Mapping):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (tuple, list, set, frozenset)):
            pending.extend(item)
        elif not isinstance(item, (str, bytes, int, float, bool, type(None), type)):
            # Rich/Textual prepared values may use slots rather than dataclasses.
            if hasattr(item, "__dict__"):
                pending.append(vars(item))
            for base in type(item).__mro__:
                slots = base.__dict__.get("__slots__", ())
                for name in (slots,) if isinstance(slots, str) else slots:
                    if name not in {"__dict__", "__weakref__"} and hasattr(item, name):
                        pending.append(getattr(item, name))
    return total


class PreparationRuntime:
    """Application-owned cache and in-flight work shared across every consumer.

    Model and render admission are separate, so a backlog of CPU rendering
    cannot consume all model slots. A waiter cancellation leaves actual work
    admitted until completion. Cached results are materialized on worker delivery:
    native consumers may mutate tokens without corrupting another view's result.
    """

    def __init__(self, renderer: Renderer, *, max_entries: int = 256,
                 max_bytes: int = 64 * 1024 * 1024, max_pending: int = 32) -> None:
        for name, value in (("max_entries", max_entries), ("max_bytes", max_bytes), ("max_pending", max_pending)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.renderer = renderer
        self.max_entries, self.max_bytes, self.max_pending = max_entries, max_bytes, max_pending
        self._ready: OrderedDict[WorkKey, tuple[PreparedValue, int]] = OrderedDict()
        self._pending: dict[WorkKey, asyncio.Task[PreparedValue]] = {}
        self._admitted = dict.fromkeys(WorkLane, 0)
        self._threads = asyncio.Semaphore(4)
        self._thread_tasks: set[asyncio.Task] = set()
        self._changed = asyncio.Event()
        self._closed = False
        self._shutdown: asyncio.Task[None] | None = None
        self.retained_bytes = 0
        self.hits = self.misses = self.shared = 0

    async def run_thread(self, function, *args):
        if self._closed:
            raise asyncio.CancelledError
        await self._threads.acquire()
        if self._closed:
            self._threads.release()
            raise asyncio.CancelledError
        task = asyncio.create_task(asyncio.to_thread(function, *args), name="preparation-thread")
        self._thread_tasks.add(task)

        def finished(completed):
            self._thread_tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()
            self._threads.release()

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    def discard_scope(self, scope: PreparationScope) -> None:
        scope.closed = True
        for key in tuple(self._ready):
            if key.scope is scope:
                _, size = self._ready.pop(key)
                self.retained_bytes -= size
        self._changed.set()

    async def submit(self, work: PreparationWork[ResultT]) -> ResultT:
        if self._closed:
            raise asyncio.CancelledError
        key = await work.identity(self)
        while True:
            if self._closed or key.scope is not None and key.scope.closed:
                raise asyncio.CancelledError
            if cached := self._ready.get(key):
                self._ready.move_to_end(key)
                self.hits += 1
                return cast(ResultT, await self._deliver(key, cached[0]))
            if pending := self._pending.get(key):
                self.shared += 1
                break
            if self._admitted[work.lane] < self.max_pending:
                self.misses += 1
                self._admitted[work.lane] += 1
                pending = asyncio.create_task(self._execute(key, work), name=f"prepare-{type(work).__name__}")
                self._pending[key] = pending

                def finished(completed, lane=work.lane):
                    self._pending.pop(key, None)
                    self._admitted[lane] -= 1
                    if not completed.cancelled():
                        completed.exception()
                    self._changed.set()

                pending.add_done_callback(finished)
                break
            self._changed.clear()
            await self._changed.wait()
        result = await asyncio.shield(pending)
        return cast(ResultT, await self._deliver(key, result))

    async def _deliver(self, key: WorkKey, result: PreparedValue[ResultT]) -> ResultT:
        """Validate at the final delivery boundary, including the worker-copy await."""
        if self._closed or key.scope is not None and key.scope.closed:
            raise asyncio.CancelledError
        copied = await self.run_thread(result.materialize)
        if self._closed or key.scope is not None and key.scope.closed:
            raise asyncio.CancelledError
        return copied

    async def _execute(self, key: WorkKey, work: PreparationWork[ResultT]) -> PreparedValue[ResultT]:
        result = await work.execute(self)
        prepared = await self.run_thread(work.store_result, result)
        if work.retain_result:
            size = prepared.size
            if not self._closed and (key.scope is None or not key.scope.closed) and size <= self.max_bytes:
                while self._ready and (len(self._ready) >= self.max_entries
                                       or self.retained_bytes + size > self.max_bytes):
                    _, (_, old_size) = self._ready.popitem(last=False)
                    self.retained_bytes -= old_size
                self._ready[key] = prepared, size
                self.retained_bytes += size
        return prepared

    async def aclose(self) -> None:
        self._closed = True
        self._changed.set()
        if self._shutdown is None:
            self._shutdown = asyncio.create_task(self._close(), name="preparation-shutdown")
        await asyncio.shield(self._shutdown)

    async def _close(self) -> None:
        if self._pending:
            await asyncio.gather(*tuple(self._pending.values()), return_exceptions=True)
        if self._thread_tasks:
            await asyncio.gather(*tuple(self._thread_tasks), return_exceptions=True)
        self._ready.clear()
        self.retained_bytes = 0
        await self.renderer.aclose()


class PreparedRenderer(Renderer):
    """Expose the existing renderer API through shared preparation by default."""

    def __init__(self, runtime: PreparationRuntime) -> None:
        self.runtime = runtime

    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        return await self.runtime.submit(RenderPreparation(task))

    async def warm_up(self, *, project: Path, ansi: bool, dark: bool) -> None:
        await self.runtime.renderer.warm_up(project=project, ansi=ansi, dark=dark)

    async def aclose(self) -> None:
        await self.runtime.aclose()
