"""The shared preparation lattice fills one runway before and after motion settles."""

from dataclasses import dataclass
from types import SimpleNamespace

from toad.client.history_pager import (
    DirectionalPreparation,
    NEWER_END,
    OLDER_END,
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

    assert lookahead.demand.read_rows(lookahead, None, OLDER_END, lookahead.window.runway_value) == 80
    assert lookahead.demand.read_rows(lookahead, None, NEWER_END, lookahead.window.runway_value) == 0

    lookahead.settle()

    assert lookahead.demand.read_rows(lookahead, None, OLDER_END, lookahead.window.runway_value) == 40
    assert lookahead.demand.read_rows(lookahead, None, NEWER_END, lookahead.window.runway_value) == 40


def test_stationary_runway_deficit_requests_the_next_source_page():
    lookahead = preparation(above=12, below=60)
    requested = []
    history = SimpleNamespace(
        selected_categories={object},
        follows_source_tail=False,
        draws_rows=True,
        filter=SimpleNamespace(active=False),
        has_more=lambda end: True,
        request_page=requested.append,
    )

    lookahead.prepare_source(history)

    assert requested == [OLDER_END]
