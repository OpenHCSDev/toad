"""Installed ingress refuses an invalid gate before executing a child."""

import asyncio
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory

from agent_comms.errors import RelationViolationError
from agent_comms.maintenance_barrier import MaintenanceBarrier
from agent_comms.acp_ingress import AcpIngress
from agent_comms.route_selection import RouteSelection
from toad.acp.shell_command import ShellCommand


def admitted_spawn(command, *, env=None, cwd=None, **options):
    """Spawn one shell command through Core's ACP ingress admission."""
    env = dict(os.environ if env is None else env)
    cwd = Path(cwd if cwd is not None else os.getcwd()).resolve()
    selection = RouteSelection.for_child(env, cwd)
    return AcpIngress(selection, cwd).spawn(
        ShellCommand.current().argv(command), env=env, **options)


async def main():
    with TemporaryDirectory(prefix="maintenance-") as directory:
        root = Path(directory)
        os.environ["AGENT_COMMS_ROOT"] = str(root / "wire")
        output = root / "executed"
        command = shlex.join((sys.executable, "-c", f"from pathlib import Path; Path({str(output)!r}).touch()"))
        child = await admitted_spawn(command)
        assert (await child.wait()).successful and output.exists()
        output.unlink()
        gate = MaintenanceBarrier(root / "wire" / "registry.json")
        # An incomplete witness is a real closed boundary; no copied internal
        # operator, synthetic phase writer, or deprecated control API needed.
        gate.marker_path.touch(mode=0o600)
        try:
            await admitted_spawn(command)
        except RelationViolationError:
            pass
        else:
            raise AssertionError("Invalid maintenance gate launched a child")
        assert not output.exists()
    print("real ingress: open launch completed; invalid witness refused before spawn")


if __name__ == "__main__":
    asyncio.run(main())
