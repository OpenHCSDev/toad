"""Serialized cache values release result graphs and keep delivery isolation."""

import asyncio
from dataclasses import dataclass
import gc
import threading
from unittest.mock import patch
from weakref import ref

from toad.work_preparation import (
    ContentAddressedWork, PreparationRuntime, PreparationScope, ScopedWork,
    SerializedValue, SerializedWork, ThreadWork, WorkKey,
)
from work_preparation_pilot import Backend


@dataclass
class Payload:
    values: list[str]


@dataclass(frozen=True)
class EncodedWork(SerializedWork[Payload], ContentAddressedWork[Payload], ThreadWork[Payload]):
    revision: str

    @property
    def inputs(self):
        return self.revision

    def prepare(self):
        return Payload([self.revision])


@dataclass(frozen=True)
class ScopedEncodedWork(SerializedWork[Payload], ScopedWork[Payload], ThreadWork[Payload]):
    scope: PreparationScope

    @property
    def work_key(self):
        return WorkKey(type(self), "revision", self.scope)

    def prepare(self):
        return Payload(["original"])


async def main():
    runtime = PreparationRuntime(Backend())
    original = Payload(["source"])
    weak_original = ref(original)
    try:
        with patch.object(EncodedWork, "prepare", return_value=original):
            first, second = await asyncio.gather(runtime.submit(EncodedWork("one")), runtime.submit(EncodedWork("one")))
        del original
        await asyncio.sleep(0)
        gc.collect()
        assert weak_original() is None, "Cache retained the original prepared object graph"
        assert runtime.misses == 1
        first.values.append("changed by caller")
        assert second.values == ["source"]
        assert (await runtime.submit(EncodedWork("one"))).values == ["source"]

        scope = PreparationScope()
        request = ScopedEncodedWork(scope)
        await runtime.submit(request)
        entered, release = threading.Event(), threading.Event()
        materialize = SerializedValue.materialize

        def held(value):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release serialized delivery")
            return materialize(value)

        try:
            with patch.object(SerializedValue, "materialize", held):
                waiter = asyncio.create_task(runtime.submit(request))
                assert await asyncio.to_thread(entered.wait, 2)
                runtime.discard_scope(scope)
                release.set()
                try:
                    await waiter
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("Retired scope delivered serialized data")
        finally:
            release.set()
    finally:
        await runtime.aclose()

    bounded = PreparationRuntime(Backend(), max_bytes=256)
    try:
        small = EncodedWork("small")
        await bounded.submit(small)
        await bounded.submit(small)
        assert bounded.hits == 1 and 0 < bounded.retained_bytes <= bounded.max_bytes
        oversized = EncodedWork("large" * 1000)
        first = await bounded.submit(oversized)
        second = await bounded.submit(oversized)
        assert first == second and first is not second
        assert bounded.misses == 3, "Oversized encoded result entered the cache"
        assert bounded.retained_bytes <= bounded.max_bytes
    finally:
        await bounded.aclose()
    print("serialized preparation: original graph released, independent deliveries, retained-value reuse and retirement gate passed")


if __name__ == "__main__":
    asyncio.run(main())
