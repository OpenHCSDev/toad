"""Late callbacks must skip elapsed deadlines, not a still-future tick."""

from unittest.mock import patch

import pytest

from textual.timer import EventTargetGone, Timer


@pytest.mark.parametrize(
    "skip,expected",
    [(True, [(1, 1.0), (3, 3.0)]), (False, [(1, 1.0), (2, 2.5)])],
)
async def test_late_callback_keeps_next_future_deadline(skip, expected):
    clock = [0.0]
    delivered = []

    class Target:
        pass

    class ProbeTimer(Timer):
        async def _tick(self, *, next_timer, count):
            delivered.append((count, clock[0]))
            if len(delivered) == 1:
                # The callback crosses one deadline but finishes before the next.
                clock[0] += 1.5
            else:
                raise EventTargetGone

    async def sleep(delay):
        clock[0] += delay

    target = Target()
    timer = ProbeTimer(target, 1.0, skip=skip)
    with patch("textual.timer._time.get_time", lambda: clock[0]), patch("textual.timer.sleep", sleep):
        await timer._run()
    assert delivered == expected


async def test_finite_timer_does_not_skip_its_remaining_future_tick():
    clock = [0.0]
    delivered = []

    class Target:
        pass

    class ProbeTimer(Timer):
        async def _tick(self, *, next_timer, count):
            delivered.append(count)
            if count == 1:
                clock[0] += 1.5

    async def sleep(delay):
        clock[0] += delay

    target = Target()
    timer = ProbeTimer(target, 1.0, repeat=2, skip=True)
    with patch("textual.timer._time.get_time", lambda: clock[0]), patch("textual.timer.sleep", sleep):
        await timer._run()
    assert delivered == [1, 3]
