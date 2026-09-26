"""Actual Agent start/spawn/send keeps one canonical admitted wire root."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_comms.maintenance_barrier import MaintenanceBarrier
from toad.acp.agent import Agent


async def main() -> None:
    with TemporaryDirectory(prefix="toad-maint-agent-root-") as directory:
        root = Path(directory)
        opened = root / "open"
        retarget = root / "retarget"
        opened.mkdir()
        retarget.mkdir()
        alias = root / "alias"
        alias.symlink_to(opened, target_is_directory=True)
        entered, release = asyncio.Event(), asyncio.Event()
        spawn_env = []

        async def empty():
            return b""

        async def fake_spawn(*_args, **kwargs):
            spawn_env.append(kwargs["env"].copy())
            return SimpleNamespace(
                pid=123, returncode=0,
                stdin=SimpleNamespace(write=lambda _: None),
                stdout=SimpleNamespace(readline=empty),
            )

        with patch.dict(
            os.environ, {"AGENT_COMMS_ROOT": str(alias), "XDG_STATE_HOME": str(root / "state")}
        ), patch("asyncio.create_subprocess_shell", fake_spawn):
            agent = Agent(root, {"name": "fake", "run_command": {"*": "true"}}, "beta")
            agent._log_file_path = root / "fake.log"
            agent.run = AsyncMock()
            agent._process_group_alive = lambda _: False
            original = agent._run_agent

            async def delayed():
                entered.set()
                await release.wait()
                await original()

            agent._run_agent = delayed
            await agent.start()
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert agent._maintenance_root == opened
            assert agent._maintenance_env["AGENT_COMMS_ROOT"] == str(opened)
            alias.unlink()
            alias.symlink_to(retarget, target_is_directory=True)
            release.set()
            await asyncio.wait_for(agent._agent_task, timeout=5)
            assert spawn_env[0]["AGENT_COMMS_ROOT"] == str(opened)

            # Pausing the retargeted alias does not affect the actual child;
            # pausing the admitted wire must block its subsequent prompt write.
            MaintenanceBarrier(retarget / "registry.json").begin("fixture")
            writes = []
            agent._process = SimpleNamespace(stdin=SimpleNamespace(write=writes.append))
            prompt = SimpleNamespace(
                body={"method": "session/prompt"}, body_json=b'{"method":"session/prompt"}'
            )
            agent.send(prompt)
            assert len(writes) == 1
            MaintenanceBarrier(opened / "registry.json").begin("fixture")
            try:
                agent.send(prompt)
            except Exception:
                pass
            else:
                raise AssertionError("Agent wrote to paused admitted wire")
            assert len(writes) == 1
            agent._process = None
            if agent._task:
                await agent._task
    print("actual Agent.start/spawn/send canonical root survives alias retarget: PASS")


if __name__ == "__main__":
    asyncio.run(main())
