"""What a frame does, counted. Shared: nothing here is a toolkit's."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from toad import paths


class FrameWork:
    """What a frame does, counted: the Python functions it enters and the Qt calls it makes.

    A time says how fast this machine did a frame's work; a count says what the work was,
    and is the same on a desktop and a phone. A desktop paints a row that lays its text out
    again, reads its model and builds its fonts for every frame in a fraction of a
    millisecond, so a time there never said that a frame in which no data changed was
    deriving anything (Tristan, 2026-11-22: "the computer is too fast and it's masking bad
    architecture"). A frame draws what was prepared when the data changed: the calls it
    makes beyond drawing are what this names.

    Asked for with `TOAD_FRAME_WORK=1` or a `frame-work` file beside `frame-probe`, since
    counting every call slows the frame it counts. The summary's `work` line gives, per
    frame, the Python functions entered and the calls into Qt (and other C functions), then
    the ones entered most."""

    NAMED = 12

    def __init__(self) -> None:
        self.frames = 0
        # Per entry (a Python function Qt itself called: a paintEvent, a delegate's paint, a
        # model's data): how often Qt entered it, the Python functions entered under it and
        # the calls into Qt and other C functions made under it.
        self.entries: dict[object, list[int]] = {}
        self.entry: list[int] | None = None
        self.depth = 0
        self.outside: object = None

    @classmethod
    def requested(cls) -> bool:
        return bool(os.environ.get("TOAD_FRAME_WORK")) or (paths.get_state() / "frame-work").is_file()

    def began(self, outside: object) -> None:
        """Count from here; ``outside`` is the code of the function delivering the event,
        whose direct callees are the entries."""
        self.outside, self.entry, self.depth = outside, None, 0
        sys.setprofile(self.counted)

    def ended(self) -> None:
        sys.setprofile(None)
        self.frames += 1

    def counted(self, frame, event: str, arg: object) -> None:
        if event == "call":
            if self.entry is None:
                # The delivering function delivers the frame's own events too (each widget's
                # paint), from inside itself: it is never an entry, and what it calls is.
                if frame.f_code is self.outside or frame.f_back is None or frame.f_back.f_code is not self.outside:
                    return
                self.entry = self.entries.setdefault(frame.f_code, [0, 0, 0])
                self.entry[0] += 1
            self.depth += 1
            self.entry[1] += 1
        elif event == "return":
            if self.entry is not None:
                self.depth -= 1
                if not self.depth:
                    self.entry = None
        elif event == "c_call" and self.entry is not None:
            self.entry[2] += 1

    @staticmethod
    def named(code: object) -> str:
        return f"{Path(code.co_filename).stem}.{code.co_qualname}"

    def line(self) -> str:
        """`work frames=N python=P/frame qt=Q/frame | entry ExP+Q ...`: per frame, the Python
        functions entered and the C calls made; then, for the entries that did most, how
        often a frame entered each (E) and the Python (P) and C (Q) calls under it."""
        frames = max(1, self.frames)
        most = sorted(self.entries.items(), key=lambda entry: -(entry[1][1] + entry[1][2]))[:self.NAMED]
        entries = " ".join(f"{self.named(code)} {entered / frames:.1f}x{python / frames:.0f}+{native / frames:.0f}"
                           for code, (entered, python, native) in most)
        return (f"work frames={self.frames} python={sum(entry[1] for entry in self.entries.values()) / frames:.1f}/frame "
                f"qt={sum(entry[2] for entry in self.entries.values()) / frames:.1f}/frame | {entries or '(none)'}")

    def measured(self) -> dict[str, dict[str, float]]:
        """Per entry, by name: how often a frame entered it, and the Python functions entered
        and the C calls made under one entry of it."""
        frames = max(1, self.frames)
        by_name: dict[str, list[int]] = {}
        for code, counts in self.entries.items():
            total = by_name.setdefault(self.named(code), [0, 0, 0])
            for place, count in enumerate(counts):
                total[place] += count
        return {name: {"entries_per_frame": round(entered / frames, 2),
                       "python_per_entry": round(python / entered, 1),
                       "c_per_entry": round(native / entered, 1)}
                for name, (entered, python, native) in sorted(by_name.items())}

    def reset(self) -> None:
        self.frames = 0
        self.entries.clear()
