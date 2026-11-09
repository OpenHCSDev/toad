"""The selected view is published; its target is derived live from it on every read.

Root applicability is the view's own belongs_to_wire. A cleared source publishes no view.
Nothing caches the target, so a change in the view's navigation_target is seen on the next read.
"""

from pathlib import Path

from toad.navigation_target import NoTarget
from toad.workspace_sessions import VisiblePublication


class FakeTarget:
    pass


class FakeView:
    def __init__(self, root: Path | None, target: object) -> None:
        self.root = root
        self.navigation_target = target

    def belongs_to_wire(self, root: Path) -> bool:
        return self.root is None or self.root == root


def test_a_bound_view_answers_only_for_its_own_root():
    target = FakeTarget()
    publication = VisiblePublication(FakeView(Path("/a"), target))
    assert publication.target_for(Path("/a")) is target
    assert isinstance(publication.target_for(Path("/b")), NoTarget)


def test_an_unbound_view_answers_for_any_root():
    target = FakeTarget()
    publication = VisiblePublication(FakeView(None, target))
    assert publication.target_for(Path("/a")) is target
    assert publication.target_for(Path("/b")) is target


def test_no_root_gets_no_target_even_from_a_bound_view():
    publication = VisiblePublication(FakeView(Path("/a"), FakeTarget()))
    assert isinstance(publication.target_for(None), NoTarget)


def test_a_cleared_source_publishes_nothing_for_any_root():
    publication = VisiblePublication(None)
    assert isinstance(publication.target_for(Path("/a")), NoTarget)
    assert isinstance(publication.target_for(Path("/b")), NoTarget)


def test_the_target_is_read_live_from_the_view_not_cached():
    view = FakeView(Path("/a"), FakeTarget())
    publication = VisiblePublication(view)
    renamed = FakeTarget()
    view.navigation_target = renamed
    assert publication.target_for(Path("/a")) is renamed
