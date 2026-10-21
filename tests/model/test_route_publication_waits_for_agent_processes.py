"""Stopping an agent retires its whole process group before the default route is published."""

import asyncio
import os
import shlex
import signal
import sys
from unittest.mock import patch

import psutil
import agent_comms.private_nk_entrypoint as private_nk_entrypoint
from agent_comms.active_route import publish_active_route
from agent_comms.child_process import AttachedChild
from agent_comms.launch_root import LaunchRoot
from agent_comms.route_selection import current_root

from support.routes import private_root, select_root_by_default_route, selecting_route


def live_members(group: int) -> list[int]:
    found = []
    for member in psutil.process_iter():
        try:
            if os.getpgid(member.pid) == group and member.status() != psutil.STATUS_ZOMBIE:
                found.append(member.pid)
        except (ProcessLookupError, psutil.NoSuchProcess):
            pass
    return found


async def test_stopping_an_agent_ends_its_process_group_before_the_new_route_is_published(app_agents, tmp_path, monkeypatch):
    from toad.acp.shell_command import ShellCommand

    tmp_path.chmod(0o700)
    for name in ("CONFIG", "DATA", "STATE"):
        monkeypatch.setenv(f"XDG_{name}_HOME", str(tmp_path / name.lower()))
    home = select_root_by_default_route(monkeypatch, tmp_path)
    old = home / ".agent-comms"
    old.mkdir(mode=0o700)
    program = ("import subprocess,sys,time; "
               "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
               "print(child.pid,flush=True); time.sleep(60)")
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(program)}"
    new_root = private_root(tmp_path / "wire", tmp_path, "PRIVATE-ONLY")
    route = selecting_route(new_root)
    assert current_root() == old

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
        with patch.object(private_nk_entrypoint, "_trusted_package", lambda _: None):
            publish_active_route(route)
        assert current_root() == new_root
    finally:
        if live_members(group):
            os.killpg(group, signal.SIGKILL)
        if process.returncode is None:
            await process.wait()
