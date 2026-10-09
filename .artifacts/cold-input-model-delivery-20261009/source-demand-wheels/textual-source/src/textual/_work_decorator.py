"""
A decorator used to create [workers](/guide/workers).
"""

from __future__ import annotations

from functools import partial, wraps
from inspect import iscoroutinefunction
from typing import TYPE_CHECKING, Callable, Coroutine, TypeVar, Union, cast, overload

from typing_extensions import ParamSpec, TypeAlias

if TYPE_CHECKING:
    from textual.worker import Worker


FactoryParamSpec = ParamSpec("FactoryParamSpec")
DecoratorParamSpec = ParamSpec("DecoratorParamSpec")
ReturnType = TypeVar("ReturnType")

Decorator: TypeAlias = Callable[
    [
        Union[
            Callable[DecoratorParamSpec, ReturnType],
            Callable[DecoratorParamSpec, Coroutine[None, None, ReturnType]],
        ]
    ],
    Callable[DecoratorParamSpec, "Worker[ReturnType]"],
]


class WorkerDeclarationError(Exception):
    """An error in the declaration of a worker method."""


if TYPE_CHECKING:

    @overload
    def work(
        method: Callable[FactoryParamSpec, Coroutine[None, None, ReturnType]],
        *,
        name: str = "",
        group: str = "default",
        exit_on_error: bool = True,
        exclusive: bool = False,
        description: str | None = None,
        thread: bool = False,
    ) -> Callable[FactoryParamSpec, "Worker[ReturnType]"]: ...

    @overload
    def work(
        method: Callable[FactoryParamSpec, ReturnType],
        *,
        name: str = "",
        group: str = "default",
        exit_on_error: bool = True,
        exclusive: bool = False,
        description: str | None = None,
        thread: bool = False,
    ) -> Callable[FactoryParamSpec, "Worker[ReturnType]"]: ...

    @overload
    def work(
        *,
        name: str = "",
        group: str = "default",
        exit_on_error: bool = True,
        exclusive: bool = False,
        description: str | None = None,
        thread: bool = False,
    ) -> Decorator[..., ReturnType]: ...


def work(
    method: (
        Callable[FactoryParamSpec, ReturnType]
        | Callable[FactoryParamSpec, Coroutine[None, None, ReturnType]]
        | None
    ) = None,
    *,
    name: str = "",
    group: str = "default",
    exit_on_error: bool = True,
    exclusive: bool = False,
    description: str | None = None,
    thread: bool = False,
) -> Callable[FactoryParamSpec, Worker[ReturnType]] | Decorator:
    """A decorator used to create [workers](/guide/workers).

    Args:
        method: A function or coroutine.
        name: A short string to identify the worker (in logs and debugging).
        group: A short string to identify a group of workers.
        exit_on_error: Exit the app if the worker raises an error. Set to `False` to suppress exceptions.
        exclusive: Cancel all workers in the same group.
        description: Readable description of the worker for debugging purposes.
            By default, it uses the decorated method's qualified name, without
            formatting its arguments.
        thread: Mark the method as a thread worker.
    """

    def decorator(
        method: (
            Callable[DecoratorParamSpec, ReturnType]
            | Callable[DecoratorParamSpec, Coroutine[None, None, ReturnType]]
        ),
    ) -> Callable[DecoratorParamSpec, Worker[ReturnType]]:
        """The decorator."""

        # Methods that aren't async *must* be marked as being a thread
        # worker.
        if not iscoroutinefunction(method) and not thread:
            raise WorkerDeclarationError(
                "Can not create a worker from a non-async function unless `thread=True` is set on the work decorator."
            )

        debug_description = (
            getattr(method, "__qualname__", name or "<worker>")
            if description is None
            else description
        )

        @wraps(method)
        def decorated(
            *args: DecoratorParamSpec.args, **kwargs: DecoratorParamSpec.kwargs
        ) -> Worker[ReturnType]:
            """The replaced callable."""
            from textual.dom import DOMNode

            self = args[0]
            assert isinstance(self, DOMNode)

            worker = cast(
                "Worker[ReturnType]",
                self.run_worker(
                    partial(method, *args, **kwargs),
                    name=name or method.__name__,
                    group=group,
                    description=debug_description,
                    exclusive=exclusive,
                    exit_on_error=exit_on_error,
                    thread=thread,
                ),
            )
            return worker

        return decorated

    if method is None:
        return decorator
    else:
        return decorator(method)
