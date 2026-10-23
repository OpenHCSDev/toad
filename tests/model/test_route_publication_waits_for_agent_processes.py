"""Stopping an agent retires its whole process group, including its child."""

import asyncio
import os
import shlex
import signal
import sys

import psutil
from agent_comms.child_process import AttachedChild
from agent_comms.launch_root import LaunchRoot


def live_members(group: int) -> list[int]:
    found = []
    for member in psutil.process_iter():
        try:
            if os.getpgid(member.pid) == group and member.status() != psutil.STATUS_ZOMBIE:
                found.append(member.pid)
        except (ProcessLookupError, psutil.NoSuchProcess):
            pass
    return found


async def test_stopping_an_agent_ends_its_process_group(app_agents, tmp_path):
    from toad.acp.shell_command import ShellCommand

    program = ("import subprocess,sys,time; "
               "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
               "print(child.pid,flush=True); time.sleep(60)")
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(program)}"

    process = await AttachedChild.start(
        ShellCommand.current().argv(command), env=LaunchRoot.environment(dict(os.environ)), cwd=tmp_path)
    group = process.identity.pid
    try:
        child_pid = int(await asyncio.wait_for(process.stdout.readline(), timeout=8))
        assert os.getpgid(group) == group
        assert os.getpgid(child_pid) == group
        assert {group, child_pid} <= set(live_members(group))
        agent = app_agents.detached_agent()
        agent.process.process = process
        agent.session.task = None
        agent.process.runner = None
        await agent.stop()
        assert process.returncode is not None
        assert not live_members(group), "old ACP descendant survived stop"
        assert agent.process.process is None
    finally:
        if live_members(group):
            os.killpg(group, signal.SIGKILL)
        if process.returncode is None:
            await process.wait()
