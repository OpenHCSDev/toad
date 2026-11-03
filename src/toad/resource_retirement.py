"""One original cleanup task per resource lifetime, independent of its other resources."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_comms.child_process import join_retirement


class Retirement(ABC):
    def allows_attachment(self) -> bool:
        return True

    def done(self) -> bool:
        return False

    def begin(self, owner: RetiresResources) -> asyncio.Task[None]:
        task = asyncio.create_task(owner._retire())
        owner.retirement = StartedRetirement(task)
        owner.retirement_started(task)
        return task


@dataclass(frozen=True)
class NoRetirement(Retirement):
    """This resource lifetime has not started cleanup."""


@dataclass(frozen=True)
class StartedRetirement(Retirement):
    task: asyncio.Task[None]

    def allows_attachment(self) -> bool:
        return False

    def done(self) -> bool:
        return self.task.done()

    def begin(self, owner: RetiresResources) -> asyncio.Task[None]:
        return self.task


class RetiresResources(ABC):
    # The shared default is an immutable, resource-free value. Starting or
    # reopening changes only the individual owner's selected retirement.
    retirement: Retirement = NoRetirement()

    @abstractmethod
    def close(self) -> None:
        """Close this owner's admission before selecting its cleanup task."""

    @abstractmethod
    async def _retire(self) -> None: ...

    def retirement_started(self, task: asyncio.Task[None]) -> None:
        """Owners without a completion observer need no callback."""

    def reset_retirement(self) -> None:
        self.retirement = NoRetirement()

    def begin_retirement(self) -> asyncio.Task[None]:
        self.close()
        return self.retirement.begin(self)

    async def retire(self) -> None:
        await join_retirement(self.begin_retirement())
