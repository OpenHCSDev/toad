"""The original scheduled task, shared without merging its owners' lifetimes."""
import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledTask:
    task: asyncio.Task[None]

    def done(self) -> bool:
        return self.task.done()
