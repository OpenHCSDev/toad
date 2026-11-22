"""Ambient motion's share of the thread that serves the reader."""

from __future__ import annotations

import pytest
from ui_theme.clock import AnimationClock
from ui_theme.effects import NAME_WAVE

from toad.motion import AmbientBudget


class Line:
    animation_visible = True

    def repaint(self) -> None:
        """Painted by the frontend."""


def test_ambient_motion_is_afforded_a_frame_as_often_as_keeps_it_within_its_share() -> None:
    """A phone's 27 ms frame leaves the waving names a frame every 0.18 s (15% of the
    thread); a desktop's 1 ms frame leaves them their own 20 a second."""
    scheduled: list[float | None] = []
    clock = AnimationClock(scheduled.append)
    clock.start(NAME_WAVE, Line())
    budget = AmbientBudget(clock)
    assert scheduled[-1] == 1 / NAME_WAVE.frames_per_second

    for _frame in range(40):
        budget.frame_shown(0.027)
    assert clock.ambient_interval == pytest.approx(0.027 / AmbientBudget.SHARE)
    assert scheduled[-1] == pytest.approx(0.18)

    for _frame in range(60):
        budget.frame_shown(0.001)
    assert scheduled[-1] == 1 / NAME_WAVE.frames_per_second
    # The timer was set when the afforded interval moved a step, not once a frame.
    assert len(scheduled) < 30
