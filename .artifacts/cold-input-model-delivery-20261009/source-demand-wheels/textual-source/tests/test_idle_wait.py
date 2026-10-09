"""Pilot idleness concerns the event-loop owner, not unrelated worker CPU."""

import pytest

from textual import _wait


class WorkloadClock:
    """Deterministic elapsed time with independently controlled CPU owners."""

    def __init__(self, *, ui_busy=False, worker_busy=False):
        self.wall = self.ui = self.worker = 0.0
        self.ui_busy, self.worker_busy = ui_busy, worker_busy
        self.samples = 0

    async def sleep(self, seconds):
        self.wall += seconds
        self.ui += seconds if self.ui_busy else 0
        self.worker += seconds if self.worker_busy else 0
        self.samples += 1

    def install(self, monkeypatch):
        monkeypatch.setattr(_wait, "monotonic", lambda: self.wall)
        monkeypatch.setattr(_wait, "process_time", lambda: self.ui + self.worker, raising=False)
        monkeypatch.setattr(_wait, "thread_time", lambda: self.ui, raising=False)
        monkeypatch.setattr(_wait, "sleep", self.sleep)


async def test_worker_cpu_does_not_extend_an_idle_ui_wait(monkeypatch):
    clock = WorkloadClock(worker_busy=True)
    clock.install(monkeypatch)
    await _wait.wait_for_idle(min_sleep=0, max_sleep=1)
    assert clock.samples == 1, "Unrelated worker activity extended an idle event-loop wait"
    assert clock.worker > 0 and clock.ui == 0


@pytest.mark.parametrize("worker_busy", [False, True])
async def test_active_ui_still_waits_until_the_existing_deadline(monkeypatch, worker_busy):
    clock = WorkloadClock(ui_busy=True, worker_busy=worker_busy)
    clock.install(monkeypatch)
    await _wait.wait_for_idle(min_sleep=0, max_sleep=1)
    assert 1 <= clock.wall <= 1 + _wait.SLEEP_GRANULARITY


async def test_idle_ui_still_observes_minimum_wait(monkeypatch):
    clock = WorkloadClock(worker_busy=True)
    clock.install(monkeypatch)
    await _wait.wait_for_idle(min_sleep=.1, max_sleep=1)
    assert .1 < clock.wall <= .1 + _wait.SLEEP_GRANULARITY
