"""A frame's work is counted under the function its deliverer calls (`toad.frame_work.FrameWork`)."""
from __future__ import annotations

import sys

from toad.frame_work import FrameWork


def helper() -> int:
    return len("x")


def entry() -> None:
    helper()
    helper()


def test_a_frames_calls_are_counted_under_the_function_the_deliverer_calls():
    work = FrameWork()

    def deliver() -> None:
        work.began(sys._getframe().f_code)
        try:
            entry()
            entry()
        finally:
            work.ended()

    deliver()
    deliver()

    measured = {name: facts for name, facts in work.measured().items() if name.endswith(".entry")}
    assert work.frames == 2
    assert list(measured.values()) == [{"entries_per_frame": 2.0, "python_per_entry": 3.0, "c_per_entry": 2.0}]


def test_a_deliverer_delivering_from_inside_itself_is_never_an_entry():
    """Qt delivers each widget's paint from inside the frame's own delivery: the nested
    delivery is the same function, and what it calls is the entry."""
    work = FrameWork()

    def deliver(nested: bool) -> None:
        if nested:
            entry()
            return
        work.began(sys._getframe().f_code)
        try:
            deliver(True)
        finally:
            work.ended()

    deliver(False)

    assert [name.rsplit(".", 1)[-1] for name in work.measured() if "FrameWork" not in name] == ["entry"]
