"""What a history does when its parked source publishes again or adds a page: cooperative hooks."""

from __future__ import annotations


class ResumesSource:
    """A history whose parked source can publish again or add pages.

    Every capability that cares overrides `source_resumed` or `_page_added`, calls `super()`,
    and adds its own part: committed coverage republishes what its drawn pages cover and
    reports added pages (`CommittedHistoryBase`), read marking marks the painted messages
    read (`ReadMarkedHistory`). This root is a base of each of them, so the MRO places it
    after all of them and the chain always reaches every capability a history combines.
    Before it existed, no-ops on `HistoryPager` sat ahead of `CommittedHistoryBase` in the
    committed histories, and `ReadMarkedHistory` ahead of it in Qt's, so one capability
    silently won."""

    def source_resumed(self) -> None:
        """The end of the chain: a resumed source needs nothing beyond its capabilities."""

    async def _page_added(self, page, fragments) -> None:
        """The end of the chain: a page joining this history needs nothing beyond its capabilities."""
