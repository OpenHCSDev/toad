"""The selected source publishes its target once; a consumer checks its own root on read.

The publication is the owned target plus the view it came from. Root applicability is the
view's own belongs_to_wire, so two distinct roots, an unbound view and a cleared source
must each answer for themselves without asking the source again.
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
        self.belongs_checks = 0

    def belongs_to_wire(self, root: Path) -> bool:
        self.belongs_checks += 1
        return self.root is None or self.root == root


def test_a_bound_view_answers_only_for_its_own_root():
    target = FakeTarget()
    publication = VisiblePublication(target, FakeView(Path("/a"), target))
    assert publication.target_for(Path("/a")) is target
    assert isinstance(publication.target_for(Path("/b")), NoTarget)


def test_an_unbound_view_answers_for_any_root():
    target = FakeTarget()
    publication = VisiblePublication(target, FakeView(None, target))
    assert publication.target_for(Path("/a")) is target
    assert publication.target_for(Path("/b")) is target


def test_no_root_gets_no_target_even_from_a_bound_view():
    target = FakeTarget()
    publication = VisiblePublication(target, FakeView(Path("/a"), target))
    assert isinstance(publication.target_for(None), NoTarget)


def test_a_cleared_source_publishes_nothing_for_any_root():
    publication = VisiblePublication(NoTarget(), None)
    assert isinstance(publication.target_for(Path("/a")), NoTarget)
    assert isinstance(publication.target_for(Path("/b")), NoTarget)


def test_reading_the_publication_does_not_ask_the_view_again_for_its_target():
    target = FakeTarget()
    view = FakeView(Path("/a"), target)
    publication = VisiblePublication(target, view)
    for _ in range(5):
        publication.target_for(Path("/a"))
    assert view.belongs_checks == 5, "only the root check runs per read; the target was published once"
