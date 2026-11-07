"""A plain frontend installation can open before installing a local agent runtime."""

import pytest

from agent_comms import active_route
from agent_comms.launch_root import LaunchRoot
from toad.cli import main
from toad.comms_root import LocalCoreConnection


def test_a_fresh_frontend_selects_the_route_owners_default(tmp_path, monkeypatch):
    monkeypatch.setattr(active_route, "active_route_path", lambda: tmp_path / "route.json")
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    with LaunchRoot.unstarted().selected():
        with main.make_context("toad", ["run", str(tmp_path)]) as context:
            assert context.obj == LocalCoreConnection(tmp_path / ".agent-comms")
    assert not (tmp_path / "route.json").exists()


def test_an_unreadable_published_route_is_not_a_fresh_install(tmp_path, monkeypatch):
    route = tmp_path / "route.json"
    route.write_text("not JSON")
    route.chmod(0o600)
    monkeypatch.setattr(active_route, "active_route_path", lambda: route)
    with LaunchRoot.unstarted().selected(), pytest.raises(ValueError):
        main.make_context("toad", ["run", str(tmp_path)])


def test_an_explicit_root_still_selects_that_root(tmp_path, monkeypatch):
    monkeypatch.setattr(active_route, "active_route_path", lambda: tmp_path / "route.json")
    requested = tmp_path / "another-bus"
    with LaunchRoot.unstarted().selected():
        with main.make_context(
            "toad", ["--comms-root", str(requested), "run", str(tmp_path)]
        ) as context:
            assert context.obj == LocalCoreConnection(requested)
