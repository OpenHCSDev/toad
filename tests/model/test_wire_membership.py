"""A bound session stays on its own wire and an unbound one projects whichever wire is
selected. The sidebar asks this for every row on every paint, so the bound identity resolves
its root once instead of walking the filesystem per question."""

from pathlib import Path

from toad.thread_identity import SessionIdentity


def test_a_bound_thread_belongs_only_to_its_own_wire(tmp_path: Path):
    identity = SessionIdentity.for_thread("claude-laptop", str(tmp_path / "bus"))
    (tmp_path / "bus").mkdir()

    assert identity.belongs_to_wire((tmp_path / "bus").resolve())
    assert not identity.belongs_to_wire((tmp_path / "other").resolve())


def test_an_unbound_session_projects_any_selected_wire(tmp_path: Path):
    assert SessionIdentity.for_thread("", None).belongs_to_wire(tmp_path)
    assert SessionIdentity.for_thread("draft", None).belongs_to_wire(tmp_path)

