"""The worker or timer a widget holds before it has scheduled anything."""

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


class NoTimer:
    """No timer was set; stopping it does nothing, so holders never test for absence."""

    def stop(self) -> None:
        pass


NO_TIMER = NoTimer()
