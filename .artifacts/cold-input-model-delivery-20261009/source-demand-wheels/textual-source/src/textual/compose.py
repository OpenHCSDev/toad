from __future__ import annotations

import asyncio
from types import GeneratorType
from typing import TYPE_CHECKING, Generator

if TYPE_CHECKING:
    from textual.app import App, ComposeResult
    from textual.widget import Widget

__all__ = ["compose"]


def compose(
    node: App | Widget, compose_result: ComposeResult | None = None
) -> list[Widget]:
    """Compose child widgets from a generator in the same way as [compose][textual.widget.Widget.compose].

    Example:
        ```python
            def on_key(self, event:events.Key) -> None:

                def add_key(key:str) -> ComposeResult:
                    with containers.HorizontalGroup():
                        yield Label("You pressed:")
                        yield Label(key)

                self.mount_all(
                    compose(self, add_key(event.key)),
                )
        ```

    Args:
        node: The parent node.
        compose_result: A compose result, or `None` to call `node.compose()`.

    Returns:
        A list of widgets.
    """
    composition = _compose(node, compose_result)
    try:
        while True:
            next(composition)
    except StopIteration as completed:
        return completed.value
    finally:
        composition.close()


async def compose_async(
    node: App | Widget, compose_result: ComposeResult | None = None
) -> list[Widget]:
    """Collect the same declaration without occupying the loop between children.

    Children stay private until the complete result enters registration. A
    suspended ``with`` belongs to this generator, not another pump's compose;
    lend its original stacks only while that generator is executing.
    """
    app = node.app
    composition = _compose(node, compose_result)
    try:
        while True:
            next(composition)
            compose_stack = app._compose_stacks.pop()
            composed = app._composed.pop()
            try:
                await asyncio.sleep(0)
            finally:
                app._compose_stacks.append(compose_stack)
                app._composed.append(composed)
    except StopIteration as completed:
        return completed.value
    finally:
        composition.close()


def _compose(
    node: App | Widget, compose_result: ComposeResult | None
) -> Generator[None, None, list[Widget]]:
    """Own declaration traversal and validation for both acquisition paths."""
    _rich_traceback_omit = True
    from textual.widget import MountError, Widget

    app = node.app
    nodes: list[Widget] = []
    compose_stack: list[Widget] = []
    composed: list[Widget] = []
    app._compose_stacks.append(compose_stack)
    app._composed.append(composed)
    iter_compose = None
    try:
        iter_compose = iter(
            compose_result if compose_result is not None else node.compose()
        )
        is_generator = hasattr(iter_compose, "throw")
        while True:
            try:
                child = next(iter_compose)
            except StopIteration:
                break

            if not isinstance(child, Widget):
                mount_error = MountError(
                    f"Can't mount {type(child)}; expected a Widget instance."
                )
                if is_generator:
                    iter_compose.throw(mount_error)  # type: ignore
                else:
                    raise mount_error from None

            try:
                child.id
            except AttributeError:
                mount_error = MountError(
                    "Widget is missing an 'id' attribute; did you forget to call super().__init__()?"
                )
                if is_generator:
                    iter_compose.throw(mount_error)  # type: ignore
                else:
                    raise mount_error from None

            if composed:
                nodes.extend(composed)
                composed.clear()
            if compose_stack:
                try:
                    compose_stack[-1].compose_add_child(child)
                except Exception as error:
                    if is_generator:
                        # So the error is raised inside the generator
                        # This will generate a more sensible traceback for the dev
                        iter_compose.throw(error)  # type: ignore
                    else:
                        raise
            else:
                nodes.append(child)
            yield
        if composed:
            nodes.extend(composed)
            composed.clear()
    finally:
        try:
            # Cancellation may occur while a declaration's with-block is open.
            # Close it with its own stacks installed before releasing them.
            if isinstance(iter_compose, GeneratorType):
                iter_compose.close()
        finally:
            app._compose_stacks.pop()
            app._composed.pop()
    return nodes
