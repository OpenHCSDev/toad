"""ACP prompt write preserves Agent.start's implicit/explicit root selection."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from default_route_pilot import private_root, route

from toad.acp.agent import Agent


async def make_agent(project: Path) -> Agent:
    agent = Agent(project, {"name": "fake", "run_command": {"*": "true"}}, None)
    agent.post_message = lambda _message: None
    agent._run_agent = AsyncMock()
    await agent.start()
    assert agent._agent_task is not None
    await agent._agent_task
    return agent


async def main() -> None:
    if os.name != "posix":
        raise RuntimeError("private route pilot needs POSIX")
    with tempfile.TemporaryDirectory(
        prefix="toad-prompt-selection-", dir="/dev/shm"
    ) as directory:
        sandbox = Path(directory)
        sandbox.chmod(0o700)
        home = sandbox / "home"
        home.mkdir(mode=0o700)
        first, first_id = private_root(sandbox / "first", sandbox, "FIRST")
        second, second_id = private_root(sandbox / "second", sandbox, "SECOND")
        project = sandbox / "project"
        project.mkdir()
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
            route(home, first, first_id)
            implicit_agent = await make_agent(project)
            assert implicit_agent._maintenance_implicit_root
            route(home, second, second_id)
            sent = []
            implicit_agent._process = SimpleNamespace(
                stdin=SimpleNamespace(write=sent.append)
            )
            prompt = SimpleNamespace(body={"method": "session/prompt"}, body_json=b"{}")
            # A later explicit process override cannot retroactively turn
            # the old-root child into an independent explicit-root writer.
            with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(first)}):
                try:
                    implicit_agent.send(prompt)
                except ValueError as error:
                    assert "route changed" in str(error)
                else:
                    raise AssertionError("stale implicit-root child prompt was written")
            assert not sent

            # Conversely an explicitly selected child remains independent
            # after the parent process drops its override.
            with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(first)}):
                explicit_agent = await make_agent(project)
            assert not explicit_agent._maintenance_implicit_root
            explicit_agent._process = SimpleNamespace(
                stdin=SimpleNamespace(write=sent.append)
            )
            explicit_agent.send(prompt)
            assert sent == [b"{}\n"]


if __name__ == "__main__":
    asyncio.run(main())
