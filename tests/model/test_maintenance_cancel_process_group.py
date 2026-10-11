"""Cancelling an ACP shell spawn while the maintenance gate holds it retires the shell and its descendant."""

import asyncio
import os
from pathlib import Path
import shlex
import signal
import sys
from unittest.mock import patch

import psutil
import pytest
from agent_comms.acp_ingress import AcpIngress
from agent_comms.child_process import AttachedChild
from agent_comms.route_selection import RouteSelection

from toad.acp.shell_command import ShellCommand


def spawn_through_ingress(command, *, env, cwd, **options):
    cwd = Path(cwd).resolve()
    return AcpIngress(RouteSelection.for_child(env, cwd), cwd).spawn(
        ShellCommand.current().argv(command), env=env, **options)


async def test_cancelled_spawn_retires_the_shell_and_its_descendant(tmp_path):
    read_fd, write_fd = os.pipe()
    loop = asyncio.get_running_loop()
    child_ready: asyncio.Future[int] = loop.create_future()
    held = asyncio.Event()
    release = asyncio.Event()
    actual = AttachedChild.start
    shell = None
    data = bytearray()

    def receive() -> None:
        data.extend(os.read(read_fd, 128))
        if b"\n" in data and not child_ready.done():
            child_ready.set_result(int(data.strip()))

    loop.add_reader(read_fd, receive)
    code = (f"import os,signal;os.write({write_fd},"
            f"str(os.getpid()).encode()+b'\\n');os.close({write_fd});signal.pause()")
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)} & wait"

    async def delayed_actual(*args, **kwargs):
        nonlocal shell
        shell = await actual(*args, **kwargs)
        await child_ready
        held.set()
        await release.wait()
        return shell

    try:
        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(tmp_path)}), patch(
            "agent_comms.child_process.AttachedChild.start", delayed_actual
        ):
            attempt = asyncio.create_task(spawn_through_ingress(
                command, pass_fds=(write_fd,), cwd=tmp_path, env=os.environ.copy()))
            await asyncio.wait_for(held.wait(), timeout=5)
            child_pid = child_ready.result()
            attempt.cancel()
            await asyncio.sleep(0)
            attempt.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(attempt, timeout=8)
            try:
                live = psutil.Process(child_pid).status() != psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                live = False
            assert not live, "shell descendant survived cancellation/gate release"
            assert shell is not None and shell.returncode is not None
    finally:
        release.set()
        loop.remove_reader(read_fd)
        os.close(read_fd)
        os.close(write_fd)
        if shell is not None:
            try:
                os.killpg(shell.identity.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await shell.wait()
