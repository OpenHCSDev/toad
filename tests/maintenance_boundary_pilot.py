"""Installed ingress refuses an invalid gate before executing a child."""

import asyncio
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory

from agent_comms.errors import RelationViolationError
from agent_comms.maintenance_barrier import MaintenanceBarrier
from toad.acp.maintenance_ingress import admitted_spawn


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
