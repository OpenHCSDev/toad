"""The shared preparation lattice fills one runway before and after motion settles."""

from dataclasses import dataclass
from types import SimpleNamespace

from toad.client.history_pager import (
    NEWER_END,
    OLDER_END,
    DirectionalPreparation,
    PresentationBudget,
    Runway,
)


@dataclass
class PreparationWindow:
    presentation_budget: PresentationBudget
    runway_value: Runway
    viewport_rows: int = 20
    unfilled_rows: int = 0
    animated_travel: float = 0
    presenting: bool = True

    def runway(self, history) -> Runway:
        return self.runway_value


def preparation(*, above: int, below: int) -> DirectionalPreparation:
    return DirectionalPreparation(PreparationWindow(
        PresentationBudget(buffer_viewports=3),
        Runway(above, below),
    ))


def test_stationary_reader_refills_the_declared_runway_on_both_sides():
    lookahead = preparation(above=12, below=35)

    assert lookahead.demand.read_rows(lookahead, None, OLDER_END, lookahead.window.runway_value) == 48
    assert lookahead.demand.read_rows(lookahead, None, NEWER_END, lookahead.window.runway_value) == 25


def test_settling_removes_velocity_without_revoking_the_runway():
    lookahead = preparation(above=20, below=20)
    lookahead.demand = lookahead.demand.moved(-100, 1)

    expected = int(100 * lookahead.budget.lookahead_seconds) - 20
    assert lookahead.demand.read_rows(lookahead, None, OLDER_END, lookahead.window.runway_value) == expected
    assert lookahead.demand.read_rows(lookahead, None, NEWER_END, lookahead.window.runway_value) == 0

    lookahead.settle()

    assert lookahead.demand.read_rows(lookahead, None, OLDER_END, lookahead.window.runway_value) == 40
    assert lookahead.demand.read_rows(lookahead, None, NEWER_END, lookahead.window.runway_value) == 40


def test_default_budget_keeps_generous_upward_runway_and_fast_fling_lookahead():
    from toad.client.history import WireSource

    budget = PresentationBudget()
    assert budget.buffer_viewports >= 5
    assert budget.destination_pages >= 4
    assert budget.batch_items >= 12
    assert budget.lookahead_seconds >= 2.0
    assert budget.delivery_safety_factor >= 3.0
    assert WireSource.tail_limit >= 20

    # On a 2000px phone viewport with 4 viewports (8000px) still above the screen,
    # even the very start of an upward drag triggers immediate older-page preparation.
    window = PreparationWindow(budget, Runway(above=8000, below=0), viewport_rows=2000)
    lookahead = DirectionalPreparation(window)
    lookahead.demand = lookahead.demand.moved(-3000, 1)
    assert lookahead.demand.read_rows(lookahead, None, OLDER_END, window.runway_value) >= 2000


def test_stationary_runway_deficit_requests_the_next_source_page():
    from toad.transcript_filter import NoFilter

    lookahead = preparation(above=12, below=60)
    requested = []
    history = SimpleNamespace(
        selected_categories={object},
        follows_source_tail=False,
        draws_rows=True,
        has_more=lambda end: True,
        request_page=requested.append,
    )
    history.filter = NoFilter(history)

    lookahead.prepare_source(history)

    assert requested == [OLDER_END]
