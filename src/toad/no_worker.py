"""The worker a widget holds before it has scheduled any work."""

from __future__ import annotations


class NoWorker:
    """No work was scheduled; queries need no absence branch or native task."""

    @property
    def is_finished(self) -> bool:
        return True

    @property
    def is_running(self) -> bool:
        return False

    @property
    def error(self) -> None:
        return None
