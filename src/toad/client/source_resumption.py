"""What a history does when its parked source publishes again: one cooperative hook."""

from __future__ import annotations


class ResumesSource:
    """A history whose parked source can publish again.

    Every capability that cares what a resume means overrides `source_resumed`, calls
    `super().source_resumed()` and adds its own part: committed coverage republishes what its
    drawn pages cover (`CommittedHistoryBase`), read marking marks the painted messages read
    (`ReadMarkedHistory`). This root is a base of each of them, so the MRO places it after all
    of them and the chain always reaches every capability a history combines. Before it existed,
    a no-op on `HistoryPager` sat ahead of `CommittedHistoryBase` in the TUI's committed
    histories, and `ReadMarkedHistory` ahead of it in Qt's, so one capability silently won."""

    def source_resumed(self) -> None:
        """The end of the chain: a resumed source needs nothing beyond its capabilities."""
