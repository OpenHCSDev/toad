"""Read-ahead speed comes from a gesture's distance over its duration, so terminal input
delivered in clumps (several wheel reports in one read, as over SSH) measures the same
speed as the same rows delivered steadily."""

from toad.widgets.presentation_window import StationaryPreparation

IDLE = 0.25  # the first report after a pause is capped at the idle interval


def measured(gaps: list[float]) -> float:
    demand = StationaryPreparation().moved(-1, IDLE)
    for gap in gaps:
        demand = demand.moved(-1, gap)
    return demand.rows(1.0)


def test_clumped_and_steady_reports_of_the_same_travel_measure_the_same_speed():
    steady = measured([0.05] * 9)
    # The same nine reports over the same 0.45 s, delivered as two clumps.
    clumped = measured([1e-6] * 4 + [0.45 - 8e-6] + [1e-6] * 4)
    assert steady < 0 and clumped < 0
    assert 0.9 < clumped / steady < 1.1


def test_one_near_zero_gap_does_not_set_the_speed():
    # The old per-gap estimate made this ten rows per microsecond.
    assert abs(measured([1e-6])) == 2 / (IDLE + 1e-6)


def test_reversal_starts_a_new_gesture():
    demand = StationaryPreparation().moved(-5, IDLE).moved(1, 0.1)
    assert demand.rows(1.0) == 1 / 0.1
