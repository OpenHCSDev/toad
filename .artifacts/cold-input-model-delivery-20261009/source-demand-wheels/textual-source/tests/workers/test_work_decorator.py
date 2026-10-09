import asyncio
from time import sleep
from typing import Callable, List, Tuple

import pytest

from textual import work
from textual._work_decorator import WorkerDeclarationError
from textual.app import App
from textual.worker import Worker, WorkerState, WorkType


async def test_worker_descriptions_do_not_format_call_payloads():
    from functools import partial

    class Payload:
        repr_calls = 0

        def __repr__(self):
            self.repr_calls += 1
            raise RuntimeError("Worker diagnostics must not format payloads")

    async def partially_declared(node, original, *, selected):
        return original, selected

    class DescriptionApp(App):
        partial_task = work(
            partial(partially_declared, selected="declared selection"),
            name="named partial",
        )

        @work
        async def retain(self, original, *, selected):
            return original, selected

        @work(description="")
        async def empty(self, original):
            return original

        @work(description="explicit diagnostic")
        async def explicit(self, original):
            return original

        @work(thread=True)
        def threaded(self, original):
            return original

    payload = Payload()
    selected = Payload()
    app = DescriptionApp()
    async with app.run_test():
        decorated = app.retain(payload, selected=selected)
        empty = app.empty(payload)
        explicit = app.explicit(payload)
        threaded = app.threaded(payload)
        declared_partial = app.partial_task(payload)

        async def receive(original):
            return original

        direct = app.run_worker(partial(receive, payload), name="direct", start=False)
        direct_empty = app.run_worker(
            partial(receive, payload), name="direct empty", description="", start=False
        )
        long = "explicit " * 150
        direct_long = app.run_worker(
            partial(receive, payload), description=long, start=False
        )
        assert decorated.description.endswith("DescriptionApp.retain")
        assert empty.description == direct_empty.description == ""
        assert explicit.description == "explicit diagnostic"
        assert direct.description == "direct"
        assert declared_partial.description == "named partial"
        assert direct_long.description == long[:1000] + "..."
        assert payload.repr_calls == selected.repr_calls == 0
        for worker in (decorated, empty, explicit, threaded, declared_partial, direct, direct_empty, direct_long):
            repr(worker)
        assert payload.repr_calls == selected.repr_calls == 0
        app.workers.start_all()
        assert await decorated.wait() == (payload, selected)
        assert await declared_partial.wait() == (payload, "declared selection")
        for worker in (empty, explicit, threaded, direct, direct_empty, direct_long):
            assert await worker.wait() is payload
        await app.workers.wait_for_complete()
        assert payload.repr_calls == selected.repr_calls == 0


class WorkApp(App):
    worker: Worker

    def __init__(self) -> None:
        super().__init__()
        self.states: list[WorkerState] = []

    @work
    async def async_work(self) -> str:
        await asyncio.sleep(0.1)
        return "foo"

    @work(thread=True)
    async def async_thread_work(self) -> str:
        await asyncio.sleep(0.1)
        return "foo"

    @work(thread=True)
    def thread_work(self) -> str:
        sleep(0.1)
        return "foo"

    def launch(self, worker) -> None:
        self.worker = worker()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        self.states.append(event.state)


async def work_with(launcher: Callable[[WorkApp], WorkType]) -> None:
    """Core code for testing a work decorator."""
    app = WorkApp()
    async with app.run_test() as pilot:
        app.launch(launcher(app))
        await app.workers.wait_for_complete()
        result = await app.worker.wait()
        assert result == "foo"
        await pilot.pause()
        assert app.states == [
            WorkerState.PENDING,
            WorkerState.RUNNING,
            WorkerState.SUCCESS,
        ]


async def test_async_work() -> None:
    """It should be possible to decorate an async method as an async worker."""
    await work_with(lambda app: app.async_work)


async def test_async_thread_work() -> None:
    """It should be possible to decorate an async method as a thread worker."""
    await work_with(lambda app: app.async_thread_work)


async def test_thread_work() -> None:
    """It should be possible to decorate a non-async method as a thread worker."""
    await work_with(lambda app: app.thread_work)


def test_decorate_non_async_no_thread_argument() -> None:
    """Decorating a non-async method without saying explicitly that it's a thread is an error."""
    with pytest.raises(WorkerDeclarationError):

        class _(App[None]):
            @work
            def foo(self) -> None:
                pass


def test_decorate_non_async_no_thread_is_false() -> None:
    """Decorating a non-async method and saying it isn't a thread is an error."""
    with pytest.raises(WorkerDeclarationError):

        class _(App[None]):
            @work(thread=False)
            def foo(self) -> None:
                pass


class NestedWorkersApp(App[None]):
    def __init__(self, call_stack: List[str]):
        self.call_stack = call_stack
        super().__init__()

    def call_from_stack(self):
        if self.call_stack:
            call_now = self.call_stack.pop()
            getattr(self, call_now)()

    @work(thread=False)
    async def async_no_thread(self):
        self.call_from_stack()

    @work(thread=True)
    async def async_thread(self):
        self.call_from_stack()

    @work(thread=True)
    def thread(self):
        self.call_from_stack()


@pytest.mark.parametrize(
    "call_stack",
    [  # from itertools import product; list(product("async_no_thread async_thread thread".split(), repeat=3))
        ("async_no_thread", "async_no_thread", "async_no_thread"),
        ("async_no_thread", "async_no_thread", "async_thread"),
        ("async_no_thread", "async_no_thread", "thread"),
        ("async_no_thread", "async_thread", "async_no_thread"),
        ("async_no_thread", "async_thread", "async_thread"),
        ("async_no_thread", "async_thread", "thread"),
        ("async_no_thread", "thread", "async_no_thread"),
        ("async_no_thread", "thread", "async_thread"),
        ("async_no_thread", "thread", "thread"),
        ("async_thread", "async_no_thread", "async_no_thread"),
        ("async_thread", "async_no_thread", "async_thread"),
        ("async_thread", "async_no_thread", "thread"),
        ("async_thread", "async_thread", "async_no_thread"),
        ("async_thread", "async_thread", "async_thread"),
        ("async_thread", "async_thread", "thread"),
        ("async_thread", "thread", "async_no_thread"),
        ("async_thread", "thread", "async_thread"),
        ("async_thread", "thread", "thread"),
        ("thread", "async_no_thread", "async_no_thread"),
        ("thread", "async_no_thread", "async_thread"),
        ("thread", "async_no_thread", "thread"),
        ("thread", "async_thread", "async_no_thread"),
        ("thread", "async_thread", "async_thread"),
        ("thread", "async_thread", "thread"),
        ("thread", "thread", "async_no_thread"),
        ("thread", "thread", "async_thread"),
        ("thread", "thread", "thread"),
        (  # Plus a longer chain to stress test this mechanism.
            "async_no_thread",
            "async_no_thread",
            "thread",
            "thread",
            "async_thread",
            "async_thread",
            "async_no_thread",
            "async_thread",
            "async_no_thread",
            "async_thread",
            "thread",
            "async_thread",
            "async_thread",
            "async_no_thread",
            "async_no_thread",
            "thread",
            "thread",
            "async_no_thread",
            "async_no_thread",
            "thread",
            "async_no_thread",
            "thread",
            "thread",
        ),
    ],
)
async def test_calling_workers_from_within_workers(call_stack: Tuple[str]):
    """Regression test for https://github.com/Textualize/textual/issues/3472.

    This makes sure we can nest worker calls without a problem.
    """
    app = NestedWorkersApp(list(call_stack))
    async with app.run_test():
        app.call_from_stack()
        # We need multiple awaits because we're creating a chain of workers that may
        # have multiple async workers, each of which may need the await to have enough
        # time to call the next one in the chain.
        for _ in range(len(call_stack)):
            await app.workers.wait_for_complete()
        assert app.call_stack == []
