"""One observation reads the registry once per announced set of registrations.

Over a remote connection a registry read is the whole document (about 9.4 MB, 4.4 s
across the Funnel). Callers arriving while that read is in flight wait for it; a failed
read is answered to every waiter and the next caller reads again.
"""

import threading
import time
from dataclasses import dataclass, field

import pytest

from agent_comms.presentation import NoRevision
from toad.comms_root import RegistryReads


@dataclass
class SlowCore:
    """Core whose registry answer is held until the test releases it."""

    answer: object = field(default_factory=object)
    released: threading.Event = field(default_factory=threading.Event)
    asked: threading.Event = field(default_factory=threading.Event)
    calls: int = 0
    failure: BaseException | None = None

    def call(self, request):
        self.calls += 1
        self.asked.set()
        self.released.wait(5)
        if self.failure is not None:
            raise self.failure
        return self.answer


@dataclass
class Access:
    revision: object = field(default_factory=NoRevision)


@dataclass
class Observation:
    core: SlowCore
    access: Access = field(default_factory=Access)


def read_together(reads: RegistryReads, observation: Observation, callers: int) -> list[object]:
    results: list[object] = [None] * callers

    def read(index: int) -> None:
        try:
            results[index] = reads.snapshot(observation)
        except BaseException as error:
            results[index] = error

    threads = [threading.Thread(target=read, args=(index,)) for index in range(callers)]
    for thread in threads:
        thread.start()
    assert observation.core.asked.wait(5)
    # Hold the read open until every caller has asked: each either waits on it or,
    # without single-flight, has started its own.
    time.sleep(0.2)
    observation.core.released.set()
    for thread in threads:
        thread.join(5)
    return results


def test_callers_during_a_read_share_it():
    reads, observation = RegistryReads(), Observation(SlowCore())

    results = read_together(reads, observation, callers=6)

    assert observation.core.calls == 1
    assert all(result is observation.core.answer for result in results)
    assert reads.snapshot(observation) is observation.core.answer
    assert observation.core.calls == 1


def test_a_failed_read_answers_its_waiters_and_the_next_caller_reads_again():
    failure = ConnectionError("the connector dropped")
    reads, observation = RegistryReads(), Observation(SlowCore(failure=failure))

    results = read_together(reads, observation, callers=4)

    assert observation.core.calls == 1
    assert all(result is failure for result in results)
    observation.core.failure = None
    assert reads.snapshot(observation) is observation.core.answer
    assert observation.core.calls == 2


if __name__ == "__main__":
    pytest.main([__file__])
