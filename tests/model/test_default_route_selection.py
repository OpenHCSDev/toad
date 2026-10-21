"""Which comms root a process, and the processes it starts, choose by default."""

import os

import pytest
from agent_comms.comms import wire
from agent_comms.route_selection import (
    child_root, current_root, implicit_root, root_is_current, run_selected_write,
)

from support.routes import private_root, publish_route, select_root_by_default_route


@pytest.fixture
def home(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    return select_root_by_default_route(monkeypatch, tmp_path)


@pytest.fixture
def roots(tmp_path, home):
    return private_root(tmp_path / "first", tmp_path, "FIRST"), private_root(tmp_path / "second", tmp_path, "SECOND")


def test_an_absent_route_selects_the_legacy_default(home):
    assert current_root() == home / ".agent-comms"


def test_a_published_route_is_what_this_process_and_its_children_use(tmp_path, home, roots):
    (first, first_id), _ = roots
    publish_route(home, first, first_id)
    assert current_root() == first
    assert child_root(os.environ, tmp_path) == first


def test_a_child_with_another_home_does_not_inherit_the_parent_route(tmp_path, home, roots):
    (first, first_id), _ = roots
    publish_route(home, first, first_id)
    with pytest.raises(ValueError, match="explicit child AGENT_COMMS_ROOT"):
        child_root(dict(os.environ, HOME=str(tmp_path / "another-home")), tmp_path)


def test_a_parent_root_override_is_explicit_and_does_not_leak_into_implicit_children(tmp_path, home, roots, monkeypatch):
    (first, first_id), (second, _) = roots
    publish_route(home, first, first_id)
    monkeypatch.setenv("AGENT_COMMS_ROOT", str(second))
    assert current_root() == second
    assert child_root(os.environ, tmp_path) == second
    implicit_child = dict(os.environ)
    del implicit_child["AGENT_COMMS_ROOT"]
    with pytest.raises(ValueError, match="explicit child AGENT_COMMS_ROOT"):
        child_root(implicit_child, tmp_path)


def test_an_unreadable_route_fails_closed_instead_of_falling_back_to_legacy(home, roots):
    (first, first_id), (second, second_id) = roots
    route = publish_route(home, second, second_id)
    route.write_text("{")
    route.chmod(0o600)
    with pytest.raises(ValueError):
        current_root()
    assert not root_is_current(second)


def test_a_route_whose_root_id_does_not_match_its_wire_is_refused(home, roots):
    (first, first_id), (second, _) = roots
    publish_route(home, second, first_id)
    with pytest.raises(ValueError, match="root ID"):
        current_root()


def test_a_world_readable_route_is_refused(home, roots):
    _, (second, second_id) = roots
    publish_route(home, second, second_id).chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        current_root()


def test_a_symlinked_route_is_not_followed(home, roots):
    (first, _), (second, second_id) = roots
    route = publish_route(home, second, second_id)
    route.unlink()
    route.symlink_to(first / "bus_meta.json")
    with pytest.raises((OSError, ValueError)):
        current_root()


def test_an_explicit_root_bypasses_a_broken_route(home, roots, monkeypatch):
    _, (second, second_id) = roots
    publish_route(home, second, second_id).write_text("{")
    assert wire(second).root == second
    monkeypatch.setenv("AGENT_COMMS_ROOT", str(second))
    assert run_selected_write(second, lambda: "explicit-root-operation",
                              implicit=implicit_root()) == "explicit-root-operation"
