"""The one loop that renders rows in the workers and holds them, for a pager's page and for a
row a view asks for as it draws."""

from __future__ import annotations

import asyncio

from toad.client.prepared_pages import HoldsRows, RowsAsked


class RecordedRows(HoldsRows):
    def __init__(self) -> None:
        self.round_trips: list[tuple[str, ...]] = []
        self.held: dict[str, str] = {}

    async def render_rows(self, waiting):
        self.round_trips.append(waiting)
        await asyncio.sleep(0)
        return tuple(unit.upper() for unit in waiting)

    def hold_row(self, waiting, row) -> None:
        self.held[waiting] = row


class LostWorker(RecordedRows):
    async def render_rows(self, waiting):
        raise ConnectionError("the worker left")


def test_waiting_rows_are_rendered_a_batch_to_a_round_trip_and_each_is_held() -> None:
    rows = RecordedRows()

    asyncio.run(rows.render_and_hold("abcde", 2))

    assert rows.round_trips == [("a", "b"), ("c", "d"), ("e",)]
    assert rows.held == dict(a="A", b="B", c="C", d="D", e="E")


def test_work_that_is_no_longer_current_stops_after_the_wave_in_flight() -> None:
    rows = RecordedRows()

    asyncio.run(rows.render_and_hold("abcde", 2, lambda: not rows.round_trips))

    assert rows.round_trips == [("a", "b"), ("c", "d")] and not rows.held


def test_rows_a_view_asks_for_in_one_turn_go_out_together_through_the_same_loop() -> None:
    async def asked() -> RecordedRows:
        rows = RecordedRows()
        view = RowsAsked(rows, 4)
        for unit in "abc":
            view.ask(unit)  # one layout asks for many rows before the loop turns
        assert not rows.round_trips
        while view.sending or view.running:
            await asyncio.sleep(0)
        view.ask("d")
        view.drop()  # asked, and forgotten before it was sent
        await asyncio.sleep(0)
        return rows

    rows = asyncio.run(asked())

    assert rows.round_trips == [("a", "b", "c")]
    assert rows.held == dict(a="A", b="B", c="C")


def test_a_render_that_fails_for_a_row_a_view_asked_for_is_reported() -> None:
    """Nothing awaits a row a view asked for: its failure reaches the loop's error report,
    where a row left plain with no error was the failure nobody saw."""
    reported: list[BaseException] = []

    async def asked() -> None:
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: reported.append(context["exception"]))
        view = RowsAsked(LostWorker(), 4)
        view.ask("a")
        while view.sending or view.running:
            await asyncio.sleep(0)

    asyncio.run(asked())

    assert [type(error) for error in reported] == [ConnectionError]
