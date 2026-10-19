"""The root an ACP child is given follows the published default route unless the child names its own."""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import agent_comms.private_nk_entrypoint as private_nk_entrypoint
from agent_comms.acp_ingress import AcpIngress
from agent_comms.active_route import ActiveRoute, publish_active_route
from agent_comms.launch_runtime import CurrentLaunchRoot
from agent_comms.route_selection import RouteSelection, current_root, run_selected_write

from support.routes import private_root, select_root_by_default_route


def spawn_through_ingress(command, *, env, cwd):
    """Spawn one shell command through Core's ACP ingress."""
    from toad.acp.shell_command import ShellCommand

    selection = RouteSelection.for_child(env, cwd)
    return AcpIngress(selection, cwd).spawn(ShellCommand.current().argv(command), env=env)


@pytest.fixture
def published(tmp_path, monkeypatch, native_package):
    """A legacy root, and a private root published as the default route."""
    tmp_path.chmod(0o700)
    for name in ("CONFIG", "DATA", "STATE"):
        monkeypatch.setenv(f"XDG_{name}_HOME", str(tmp_path / name.lower()))
    home = select_root_by_default_route(monkeypatch, tmp_path)
    legacy = home / ".agent-comms"
    legacy.mkdir(mode=0o700)
    private, private_id = private_root(tmp_path / "wire", tmp_path, "PRIVATE-ONLY")
    route = ActiveRoute(private, private_id, native_package)
    assert current_root() == legacy
    with patch.object(private_nk_entrypoint, "_trusted_package", lambda _: None):
        publish_active_route(route)
    assert current_root() == private
    return SimpleNamespace(legacy=legacy, private=private, private_id=private_id, route=route, cwd=tmp_path)


class Launches:
    """Stands in for the child process start and records the environment it was offered."""

    def __init__(self):
        self.env = {}

    async def __call__(self, _command, **kwargs):
        self.env.update(kwargs["env"])
        return SimpleNamespace(pid=123, returncode=0)


async def test_a_child_is_given_the_root_its_selection_names(published):
    for env, root in ((dict(os.environ), published.private),
                      (dict(os.environ, AGENT_COMMS_ROOT=str(published.legacy)), published.legacy)):
        launches = Launches()
        with patch("agent_comms.child_process.AttachedChild.start", launches):
            await spawn_through_ingress("fake-child", env=env, cwd=published.cwd)
        assert launches.env["AGENT_COMMS_ROOT"] == str(root)


async def test_an_explicit_prompt_holds_the_published_route_while_it_runs(published):
    explicit = RouteSelection.for_child(dict(os.environ, AGENT_COMMS_ROOT=str(published.legacy)), published.cwd)
    async with AcpIngress(explicit, published.cwd).prompt():
        assert current_root() == published.private


def test_a_write_selected_before_the_flip_is_refused_after_it(published):
    invoked = []
    with pytest.raises(ValueError):
        run_selected_write(published.legacy, invoked.append, None, root_selection=CurrentLaunchRoot(published.legacy))
    assert not invoked
