"""Selected background runs retain their original tasks through cancellation and joins."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

from toad.scheduled_task import ScheduledTask


class BackgroundRun(ABC):
    def running(self) -> bool:
        return False

    def tasks(self) -> tuple[asyncio.Task[None], ...]:
        return ()

    def cancel(self) -> None:
        """No selected run has nothing to cancel."""

    async def cancel_and_join_other(self) -> None:
        """No selected run has nothing to join."""


@dataclass(frozen=True)
class NoRun(BackgroundRun):
    """This owner has no selected background task."""


@dataclass(frozen=True)
class StartedRun(ScheduledTask, BackgroundRun):
    def running(self) -> bool:
        return not self.done()

    def tasks(self) -> tuple[asyncio.Task[None], ...]:
        return (self.task,)

    def cancel(self) -> None:
        self.task.cancel()

    async def cancel_and_join_other(self) -> None:
        if self.task is not asyncio.current_task():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class HasBackgroundRun:
    runner: BackgroundRun = NoRun()

    def clear_runner(self) -> None:
        self.runner = NoRun()


class StartsBackgroundRun(HasBackgroundRun, ABC):
    @abstractmethod
    async def run(self) -> None: ...

    def runner_started(self, task: asyncio.Task[None]) -> None:
        """Owners without a completion observer need no callback."""

    def start_runner(self) -> None:
        task = asyncio.create_task(self.run())
        self.runner = StartedRun(task)
        self.runner_started(task)
