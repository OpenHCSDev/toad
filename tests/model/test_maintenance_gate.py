"""Core's ACP ingress runs a shell command when the maintenance gate is open and refuses before spawning when it is invalid."""

import os
from pathlib import Path
import shlex
import sys

import pytest
from agent_comms.acp_ingress import AcpIngress
from agent_comms.errors import RelationViolationError
from agent_comms.maintenance_barrier import MaintenanceBarrier
from agent_comms.route_selection import RouteSelection

from toad.acp.shell_command import ShellCommand


def spawn_through_ingress(command, *, env, cwd, **options):
    """Spawn one shell command through Core's ACP ingress."""
    cwd = Path(cwd).resolve()
    return AcpIngress(RouteSelection.for_child(env, cwd), cwd).spawn(
        ShellCommand.current().argv(command), env=env, **options)


@pytest.fixture
def touch_command(tmp_path):
    output = tmp_path / "executed"
    command = shlex.join((sys.executable, "-c", f"from pathlib import Path; Path({str(output)!r}).touch()"))
    return command, output


async def test_an_open_gate_runs_the_command(tmp_path, touch_command):
    command, output = touch_command
    env = dict(os.environ) | {"AGENT_COMMS_ROOT": str(tmp_path / "wire")}
    child = await spawn_through_ingress(command, env=env, cwd=tmp_path)
    assert (await child.wait()).successful and output.exists()


async def test_an_incomplete_gate_refuses_before_any_child_is_spawned(tmp_path, touch_command):
    command, output = touch_command
    env = dict(os.environ) | {"AGENT_COMMS_ROOT": str(tmp_path / "wire")}
    (tmp_path / "wire").mkdir()
    gate = MaintenanceBarrier(tmp_path / "wire" / "registry.json")
    # An incomplete marker is a real closed boundary; no copied internal operator needed.
    gate.marker_path.touch(mode=0o600)
    with pytest.raises(RelationViolationError):
        await spawn_through_ingress(command, env=env, cwd=tmp_path)
    assert not output.exists()
