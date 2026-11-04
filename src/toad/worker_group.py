"""A kind of Textual worker: its group name and exclusivity are declared once, on the kind."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual import work
from textual.dom import DOMNode
from textual.worker import Worker


class WorkerGroup:
    """Textual groups a node's workers by name; each kind names its group once.

    Members declare `group` (and `exclusive` where a newer start cancels a
    running one). Callers start, cancel and ask about work through the kind,
    never by the group's name.
    """

    group: ClassVar[str]
    exclusive: ClassVar[bool] = False

    @classmethod
    def work[F: Callable](cls, method: F) -> F:
        """Decorate a node method so each call runs as this kind's worker."""
        return work(group=cls.group, exclusive=cls.exclusive)(method)

    @classmethod
    def run_on(cls, node: DOMNode, task: Callable[[], object], **options) -> Worker:
        return node.run_worker(task, group=cls.group, exclusive=cls.exclusive, **options)

    @classmethod
    def cancel_all(cls, node: DOMNode) -> list[Worker]:
        """Every worker of this kind on the node, including ones a newer start superseded."""
        return node.workers.cancel_group(node, cls.group)

    @classmethod
    def running_on(cls, node: DOMNode) -> bool:
        return any(worker.node is node and worker.group == cls.group and not worker.is_finished
                   for worker in node.workers)


class InputHistoryRecord(WorkerGroup):
    """Appends a sent prompt or shell command to its input history."""

    group = "history"
