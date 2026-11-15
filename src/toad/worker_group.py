"""Textual operation owner: the native Worker/DOMNode operations for each kind.

Identity and exclusivity are inherited from Formbridge's OperationKind.
This module adds only the Textual-specific start/cancel/wait methods.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from formbridge.operations import ExclusiveKind, OperationKind
from textual import work
from textual.dom import DOMNode
from textual.worker import Worker, WorkType


class WorkerGroup(OperationKind):
    """Textual operation owner: group name and exclusivity from OperationKind,
    native Worker start/cancel/wait/running on DOMNode."""

    @classmethod
    def work[F: Callable](cls, method: F) -> F:
        return work(group=cls.group, exclusive=cls.exclusive)(method)

    @classmethod
    def run_on(cls, node: DOMNode, task: WorkType[object], **options) -> Worker:
        return node.run_worker(task, group=cls.group, exclusive=cls.exclusive, **options)

    @classmethod
    def cancel_all(cls, node: DOMNode) -> list[Worker]:
        return node.workers.cancel_group(node, cls.group)

    @classmethod
    def workers_on(cls, node: DOMNode) -> tuple[Worker, ...]:
        return tuple(worker for worker in node.workers
                     if worker.node is node and worker.group == cls.group)

    @classmethod
    async def wait_on(cls, node: DOMNode) -> None:
        await asyncio.gather(*(worker.wait() for worker in cls.workers_on(node)))

    @classmethod
    def running_on(cls, node: DOMNode) -> bool:
        return any(not worker.is_finished for worker in cls.workers_on(node))


class InputHistoryRecord(WorkerGroup):
    """Appends a sent prompt or shell command to its input history."""

