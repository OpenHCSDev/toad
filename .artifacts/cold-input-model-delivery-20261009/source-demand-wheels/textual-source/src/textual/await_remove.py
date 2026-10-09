"""
An *optionally* awaitable object returned by methods that remove widgets.
"""

from __future__ import annotations

import asyncio
from asyncio import Future, Task, gather
from typing import TYPE_CHECKING, Awaitable

import rich.repr

from textual._callback import invoke
from textual._types import CallbackType
from textual.await_complete import AwaitCompletion

if TYPE_CHECKING:
    from textual.dom import DOMNode
    from textual.screen import Screen
    from textual.widget import Widget


@rich.repr.auto
class AwaitRemove(AwaitCompletion):
    """An awaitable that waits for nodes to be removed."""

    def __init__(
        self, tasks: list[Task], post_remove: CallbackType | None = None
    ) -> None:
        super().__init__()
        self._tasks = list(tasks)
        self._post_remove = post_remove
        self._completion: Future[None] | None = None
        self._finisher: Task[None] | None = None

    @classmethod
    def prune(cls, *nodes: Widget, parent: DOMNode | None = None) -> AwaitRemove:
        """Retire native scenes before awaiting their original node teardown."""
        from textual.app import ScreenStackError
        from textual.dom import NoScreen
        from textual.messages import Prune

        if not nodes:
            return cls([])
        app = nodes[0].app
        pruning_nodes: set[Widget] = set(nodes)
        for node in nodes:
            node.post_message(Prune())
            pruning_nodes.update(node.walk_children(with_self=True))
        scenes: dict[Screen, set[Widget]] = {}
        for node in pruning_nodes:
            try:
                screen = node.screen
            except (ScreenStackError, NoScreen):
                continue
            scenes.setdefault(screen, set()).add(node)
        for screen, members in scenes.items():
            if screen.focused and screen.focused in members:
                screen._reset_focus(screen.focused, list(members))
        for node in pruning_nodes:
            node._pruning = True
        for node in nodes:
            # Pruning changes display before NodeList custody is released.
            # Retire its existing projections so lazy layout cannot reinsert it.
            node._nodes.updated()
            node._invalidate_layout()
        for screen, members in scenes.items():
            screen._forget_pruned_widgets(members)

        def post_remove() -> None:
            if parent is not None:
                try:
                    screen = parent.screen
                except (ScreenStackError, NoScreen):
                    pass
                else:
                    if screen._running and screen.is_current:
                        app._update_mouse_over(screen)
                finally:
                    parent.refresh(layout=True)

        removal = cls(
            [task for node in nodes if (task := node._task) is not None], post_remove
        )
        removal.call_when_ready(app)
        return removal

    def __rich_repr__(self) -> rich.repr.Result:
        yield "tasks", self._tasks
        yield "post_remove", self._post_remove
        yield "caller", self._caller, None

    def _start(self) -> Future[None]:
        """One independently-owned teardown completion for all optional waiters."""
        if self._completion is None:
            self._completion = asyncio.get_running_loop().create_future()
            self._finisher = asyncio.create_task(self._finish(), name="complete removal")
        return self._completion

    async def _finish(self) -> None:
        assert self._completion is not None
        try:
            await gather(*self._tasks)
            if self._post_remove is not None:
                await invoke(self._post_remove)
        except asyncio.CancelledError:
            self._completion.cancel()
        except BaseException as error:
            self._completion.set_exception(error)
        else:
            self._completion.set_result(None)
        finally:
            # A retained receipt is data about completion, not an owner of the
            # pruned tree, its callbacks or task contexts.
            self._tasks.clear()
            self._post_remove = None
            self._finisher = None

    def _await(self) -> Awaitable[None]:
        current_task = asyncio.current_task()
        self_removal = current_task in self._tasks
        other_tasks = [task for task in self._tasks if task is not current_task]

        async def await_prune() -> None:
            completion = self._start()
            if self_removal:
                # A widget's handler has to return before its own message pump
                # can process Prune. The independent completion still waits for
                # that real exit before publishing the removal.
                await gather(*(asyncio.shield(task) for task in other_tasks))
                return
            await asyncio.shield(completion)

        return await_prune()
