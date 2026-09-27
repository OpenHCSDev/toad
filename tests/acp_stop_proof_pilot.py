"""Provider-free real ACP process-group retirement and unresolved-stop controls."""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from toad.acp import maintenance_ingress
from toad.acp.agent import Agent
from toad.acp.group_retirement import (
    GroupRetirementUnresolved,
    capture_accepted_group,
    live_group_members,
    signal_accepted_group,
)


def fixture_agent(path: Path, process: asyncio.subprocess.Process) -> Agent:
    agent = Agent(path, {"name": "fixture", "run_command": {"*": "true"}}, None)
    agent.post_message = lambda _message: None
    agent._process = process
    agent._process_group_id = process.pid
    agent._accepted_group = capture_accepted_group(process.pid)
    agent._task = None
    agent._agent_task = None
    return agent


async def spawn_group(path: Path) -> tuple[asyncio.subprocess.Process, int]:
    program = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
        "print(child.pid,flush=True); time.sleep(60)"
    )
    process = await asyncio.create_subprocess_shell(
        f"{shlex.quote(sys.executable)} -c {shlex.quote(program)}",
        cwd=str(path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    assert process.stdout is not None
    child_pid = int(await asyncio.wait_for(process.stdout.readline(), timeout=8))
    return process, child_pid


async def cleanup(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.returncode is None:
        await process.wait()


async def real_success() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-stop-proof-", dir="/dev/shm") as root:
        process, child = await spawn_group(Path(root))
        try:
            agent = fixture_agent(Path(root), process)
            identity = agent._accepted_group
            assert identity is not None
            assert child in {pid for pid, _ in live_group_members(identity)}
            evidence = await agent.stop()
            assert evidence is not None and evidence.accepted == identity
            assert not live_group_members(identity)
            assert agent.verify_retirement() == evidence
            assert agent._process_group_id is None
        finally:
            await cleanup(process)


async def unresolved_and_retry() -> None:
    with tempfile.TemporaryDirectory(
        prefix="toad-stop-unresolved-", dir="/dev/shm"
    ) as root:
        process, child = await spawn_group(Path(root))
        try:
            agent = fixture_agent(Path(root), process)
            identity = agent._accepted_group
            assert identity is not None
            # Suppress both signals to model a surviving group at deadline.
            with patch("toad.acp.agent.signal_accepted_group", lambda *_: None):
                try:
                    await agent.stop()
                except GroupRetirementUnresolved as error:
                    assert error.accepted == identity
                    assert child in {pid for pid, _ in error.members}
                else:
                    raise AssertionError(
                        "stop falsely succeeded with a live descendant"
                    )
            assert agent._process_group_id == identity.pgid
            assert agent._accepted_group == identity
            assert agent._retirement is None
            try:
                await agent.start()
            except GroupRetirementUnresolved:
                pass
            else:
                raise AssertionError("unretired child was restarted")
            evidence = await agent.stop()
            assert evidence is not None and evidence.accepted == identity
        finally:
            await cleanup(process)


async def cancellation_keeps_identity() -> None:
    with tempfile.TemporaryDirectory(
        prefix="toad-stop-cancel-", dir="/dev/shm"
    ) as root:
        process, _child = await spawn_group(Path(root))
        try:
            agent = fixture_agent(Path(root), process)
            identity = agent._accepted_group
            assert identity is not None
            with patch("toad.acp.agent.signal_accepted_group", lambda *_: None):
                task = asyncio.create_task(agent.stop())
                await asyncio.sleep(0)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            assert agent._process_group_id == identity.pgid
            assert agent._accepted_group == identity
            assert agent._retirement is None
            await agent.stop()
        finally:
            await cleanup(process)


async def admission_pending_never_reports_stopped() -> None:
    with tempfile.TemporaryDirectory(
        prefix="toad-stop-admission-", dir="/dev/shm"
    ) as root:
        agent = Agent(
            Path(root), {"name": "fixture", "run_command": {"*": "sleep 60"}}, None
        )
        agent.post_message = lambda _message: None
        spawned = asyncio.Event()
        release = asyncio.Event()
        holder: dict[str, asyncio.subprocess.Process] = {}

        async def delayed_spawn(*_args, **_kwargs):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            holder["process"] = process
            spawned.set()
            await release.wait()
            return process

        try:
            with patch.object(maintenance_ingress, "admitted_spawn", delayed_spawn):
                agent._agent_task = asyncio.create_task(agent._run_agent())
                await asyncio.wait_for(spawned.wait(), timeout=5)
                try:
                    await agent.stop()
                except GroupRetirementUnresolved as error:
                    assert "admission has not settled" in str(error)
                else:
                    raise AssertionError("untracked accepted child reported stopped")
                assert agent._agent_task is not None
                assert not agent._agent_task.done()
                assert holder["process"].returncode is None
                release.set()
                await asyncio.wait_for(agent._agent_task, timeout=8)
                assert agent.verify_retirement().accepted.leader_pid == (
                    holder["process"].pid
                )
        finally:
            release.set()
            if "process" in holder:
                await cleanup(holder["process"])


def pid_reuse_declines() -> None:
    from toad.acp import group_retirement

    identity = group_retirement.AcceptedGroup(os.getpid(), 0.0, os.getpgrp())
    with patch.object(group_retirement.os, "killpg") as kill:
        try:
            signal_accepted_group(identity, signal.SIGTERM)
        except GroupRetirementUnresolved:
            pass
        else:
            raise AssertionError("reused leader PID was accepted")
        kill.assert_not_called()


async def main() -> None:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("the real process-group probe requires Linux")
    await real_success()
    await unresolved_and_retry()
    await cancellation_keeps_identity()
    await admission_pending_never_reports_stopped()
    pid_reuse_declines()
    print("ACP stop proof pilots PASS")


if __name__ == "__main__":
    asyncio.run(main())
