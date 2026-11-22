"""Work on the event loop that fails with nobody waiting is shown; work someone waits for is theirs."""

from __future__ import annotations

import asyncio

from toad.client.lost_failures import LostFailures


def heard(scene) -> list[tuple[str, str]]:
    """What was shown while ``scene`` ran on a loop that hears lost failures: each failure's
    type name (or the text asyncio reported) and its title."""
    shown: list[tuple[str, str]] = []

    def show(failure, title: str) -> None:
        shown.append((failure if isinstance(failure, str) else type(failure).__name__, title))

    async def run() -> None:
        LostFailures(show).hear(asyncio.get_running_loop())
        await scene()
        for _turn in range(3):  # the ended task's waiters, then the look after them
            await asyncio.sleep(0)

    asyncio.run(run())
    return shown


async def fails() -> None:
    raise LookupError("no such view")


def test_a_task_nobody_waits_for_is_shown_when_it_fails_while_something_still_holds_it() -> None:
    held = []

    async def scene() -> None:
        held.append(asyncio.ensure_future(fails()))  # held: asyncio would never say
        held[0].set_name("open #comms")
        await asyncio.sleep(0)

    assert heard(scene) == [("LookupError", "open #comms failed")]


def test_a_failure_its_waiter_takes_is_the_waiters() -> None:
    async def awaited() -> None:
        try:
            await asyncio.ensure_future(fails())
        except LookupError:
            pass

    async def gathered() -> None:
        await asyncio.gather(asyncio.ensure_future(fails()), return_exceptions=True)

    async def cancelled() -> None:
        task = asyncio.ensure_future(asyncio.sleep(10))
        await asyncio.sleep(0)
        task.cancel()

    assert heard(awaited) == [] and heard(gathered) == [] and heard(cancelled) == []


def test_a_callback_that_raises_is_shown() -> None:
    def raises() -> None:
        raise LookupError("no such row")

    async def scene() -> None:
        asyncio.get_running_loop().call_soon(raises)
        await asyncio.sleep(0)

    (failure, title), = heard(scene)
    assert failure == "LookupError" and "Exception in callback" in title
