"""A kind of Textual worker: its group name and exclusivity are declared once, on the kind."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ClassVar

from textual import work
from textual.dom import DOMNode
from textual.worker import Worker, WorkType


class WorkerGroup:
    """Textual groups a node's workers by name; each kind names its group once.

    The kind is the identity: Textual's group name is derived from the class,
    so no member writes one. Members declare `exclusive` where a newer start
    cancels a running one. Callers start, cancel and ask about work through
    the kind, never by the group's name.
    """

    group: ClassVar[str]
    exclusive: ClassVar[bool] = False

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        # Textual names groups with a string; the class's own path is that name.
        cls.group = f"{cls.__module__}.{cls.__qualname__}"

    @classmethod
    def work[F: Callable](cls, method: F) -> F:
        """Decorate a node method so each call runs as this kind's worker."""
        return work(group=cls.group, exclusive=cls.exclusive)(method)

    @classmethod
    def run_on(cls, node: DOMNode, task: WorkType[object], **options) -> Worker:
        return node.run_worker(task, group=cls.group, exclusive=cls.exclusive, **options)

    @classmethod
    def cancel_all(cls, node: DOMNode) -> list[Worker]:
        """Every worker of this kind on the node, including ones a newer start superseded."""
        return node.workers.cancel_group(node, cls.group)

    @classmethod
    def workers_on(cls, node: DOMNode) -> tuple[Worker, ...]:
        return tuple(worker for worker in node.workers
                     if worker.node is node and worker.group == cls.group)

    @classmethod
    async def wait_on(cls, node: DOMNode) -> None:
        """Wait for the node's actual work; its original error still refuses the caller."""
        await asyncio.gather(*(worker.wait() for worker in cls.workers_on(node)))

    @classmethod
    def running_on(cls, node: DOMNode) -> bool:
        return any(not worker.is_finished for worker in cls.workers_on(node))


class InputHistoryRecord(WorkerGroup):
    """Appends a sent prompt or shell command to its input history."""

