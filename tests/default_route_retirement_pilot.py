"""Disposable accepted ACP process-group retirement before route publication.

No provider, real Toad process, installed package, or live Comms root is used.
The ACP stand-in only creates a sleeping descendant in its own process group.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import psutil
from agent_comms import cohort_foreground
from agent_comms.active_route import ActiveRoute, publish_active_route
from default_route_pilot import private_root

from toad.acp.agent import Agent
from toad.acp.maintenance_ingress import admitted_spawn
from toad.comms_root import current_root


def live_members(group: int) -> list[int]:
    result = []
    for member in psutil.process_iter():
        try:
            if (
                os.getpgid(member.pid) == group
                and member.status() != psutil.STATUS_ZOMBIE
            ):
                result.append(member.pid)
        except ProcessLookupError, psutil.NoSuchProcess:
            pass
    return result


async def main() -> None:
    if os.name != "posix" or Path("/var").is_symlink():
        raise RuntimeError("private route publication needs real /var/tmp ancestry")
    with tempfile.TemporaryDirectory(
        prefix="toad-retire-", dir="/dev/shm"
    ) as directory:
        sandbox = Path(directory)
        sandbox.chmod(0o700)
        home = sandbox / "home"
        home.mkdir(mode=0o700)
        old = home / ".agent-comms"
        old.mkdir(mode=0o700)
        program = (
            "import subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import time;time.sleep(60)']); "
            "print(child.pid,flush=True); time.sleep(60)"
        )
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote(program)}"
        with tempfile.TemporaryDirectory(
            prefix="toad-retire-private-", dir="/var/tmp"
        ) as private_dir:
            new_root, root_id = private_root(
                Path(private_dir) / "wire", sandbox, "PRIVATE-ONLY"
            )
            route = ActiveRoute(new_root, root_id, sandbox / "unused-package")
            with patch.dict(
                os.environ,
                {
                    "HOME": str(home),
                    "XDG_CONFIG_HOME": str(sandbox / "config"),
                    "XDG_DATA_HOME": str(sandbox / "data"),
                    "XDG_STATE_HOME": str(sandbox / "state"),
                },
            ):
                os.environ.pop("AGENT_COMMS_ROOT", None)
                assert current_root() == old
                process = await admitted_spawn(
                    command,
                    cwd=str(sandbox),
                    env=dict(os.environ),



                )
                group = process.identity.pid  # Toad Agent._process_group_id and OS PGID
                try:
                    assert process.stdout is not None
                    child_pid = int(
                        await asyncio.wait_for(process.stdout.readline(), timeout=8)
                    )
                    assert os.getpgid(group) == group
                    assert os.getpgid(child_pid) == group
                    assert {group, child_pid} <= set(live_members(group))
                    agent = Agent(
                        sandbox, {"name": "fixture", "run_command": {"*": "true"}}, None
                    )
                    agent.post_message = lambda _event: None
                    agent.process.process = process
                    agent.process.session_task = None
                    agent.process.runner = None
                    evidence = await agent.stop()
                    assert process.returncode is not None
                    assert not live_members(group), "old ACP descendant survived stop"
                    assert agent.process.process is None
                    with patch.object(
                        cohort_foreground, "_trusted_package", lambda _: None
                    ):
                        publish_active_route(route)
                    assert current_root() == new_root
                finally:
                    if live_members(group):
                        os.killpg(group, signal.SIGKILL)
                    if process.returncode is None:
                        await process.wait()


if __name__ == "__main__":
    asyncio.run(main())
