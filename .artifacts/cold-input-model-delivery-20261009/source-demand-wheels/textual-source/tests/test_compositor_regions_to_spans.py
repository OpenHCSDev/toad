from textual._compositor import Compositor
from textual.geometry import Region


def test_regions_to_ranges_no_regions():
    assert list(Compositor._regions_to_spans([])) == []


def test_regions_to_ranges_single_region():
    regions = [Region(0, 0, 3, 2)]
    assert list(Compositor._regions_to_spans(regions)) == [
        (0, 0, 3),
        (1, 0, 3),
    ]


def test_regions_to_ranges_partially_overlapping_regions():
    regions = [Region(0, 0, 2, 2), Region(1, 1, 2, 2)]
    assert list(Compositor._regions_to_spans(regions)) == [
        (0, 0, 2),
        (1, 0, 3),
        (2, 1, 3),
    ]


def test_regions_to_ranges_fully_overlapping_regions():
    regions = [Region(1, 1, 3, 3), Region(2, 2, 1, 1), Region(0, 2, 3, 1)]
    assert list(Compositor._regions_to_spans(regions)) == [
        (1, 1, 4),
        (2, 0, 4),
        (3, 1, 4),
    ]


def test_regions_to_ranges_disjoint_regions_different_lines():
    regions = [Region(0, 0, 2, 1), Region(2, 2, 2, 1)]
    assert list(Compositor._regions_to_spans(regions)) == [(0, 0, 2), (2, 2, 4)]


def test_regions_to_ranges_disjoint_regions_same_line():
    regions = [Region(0, 0, 1, 2), Region(2, 0, 1, 1)]
    assert list(Compositor._regions_to_spans(regions)) == [
        (0, 0, 1),
        (0, 2, 3),
        (1, 0, 1),
    ]


def test_regions_to_ranges_directly_adjacent_ranges_merged():
    regions = [Region(0, 0, 1, 2), Region(1, 0, 1, 2)]
    assert list(Compositor._regions_to_spans(regions)) == [
        (0, 0, 2),
        (1, 0, 2),
    ]


def test_damage_bands_keep_overlap_multiplicity_origins_and_empty_gaps():
    regions = [
        Region(-2, -3, 4, 4),
        Region(-2, -1, 4, 4),
        Region(2, -2, 2, 4),
        Region(9, 0, 2, 2),
        Region(3, 5, 1, 0),
        Region(6, 7, 1, -1),
        Region(100, 1000, 0, 1),
    ]
    # Equal horizontal intervals are independently owned rectangles: one can
    # end while the other still supplies damage. A one-shot input and distant
    # band retain the original reducer's order and zero-width span contract.
    assert list(Compositor._regions_to_spans(iter(regions))) == [
        (-3, -2, 2),
        (-2, -2, 4),
        (-1, -2, 4),
        (0, -2, 4), (0, 9, 11),
        (1, -2, 4), (1, 9, 11),
        (2, -2, 2),
        (1000, 100, 100),
    ]
