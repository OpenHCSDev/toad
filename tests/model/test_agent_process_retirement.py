"""An agent process ends through EOF, cancellation or an explicit stop with its child gone, its session retired and the default-route lock released; a start cancelled in preflight leaks neither."""

import asyncio
import fcntl
import os
import sys
import threading
from unittest.mock import patch

import psutil
import pytest

from support.agents import command, detached
from toad.acp.agent import Agent


@pytest.fixture
def home(tmp_path, monkeypatch):
    """The user's home is private, so the default-route lock directory is this test's own."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_COMMS_ROOT", str(tmp_path / ".agent-comms"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / ".agent-comms" / "state"))
    (tmp_path / ".agent-comms").mkdir()
    return tmp_path


def route_lock_available(home):
    directory = os.open(home / ".local/state/agent-comms", os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    finally:
        os.close(directory)


async def until(ui_condition, why):
    try:
        async with asyncio.timeout(8):
            while not ui_condition():
                await asyncio.sleep(.02)
    except TimeoutError:
        raise AssertionError(f"{why} not reached in 8s") from None


async def test_a_start_cancelled_in_preflight_releases_the_route_and_starts_no_child(home):
    from agent_comms.acp_ingress import AcpIngress

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    preflight = AcpIngress.preflight

    async def held_preflight(ingress):
        entered.set()
        try:
            assert await asyncio.to_thread(release.wait, 5), "controlled preflight was not released"
            return await preflight(ingress)
        finally:
            finished.set()

    agent = detached(home)
    with patch("agent_comms.acp_ingress.AcpIngress.preflight", held_preflight):
        start = asyncio.create_task(agent.start())
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            assert not route_lock_available(home), "start acquired no route lock"
            start.cancel()
            with pytest.raises(asyncio.CancelledError):
                await start
            assert agent.process.runner is None and agent.process.process is None
            assert route_lock_available(home), "cancelled preflight leaked the route lock"
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)
            await agent.stop()


@pytest.mark.parametrize("how", ["cancel", "stop", "eof"])
async def test_the_child_and_session_are_retired_and_the_route_released(home, how):
    pid_file = home / f"{how}.pid"
    code = (
        "import subprocess,sys,time;from pathlib import Path;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        f"Path({str(pid_file)!r}).write_text(str(p.pid));"
        + ("time.sleep(60)" if how != "eof" else "")
    )
    agent = Agent(home, command(sys.executable, "-c", code, name="Retirement", identity="retirement"), None)

    async def session():
        await asyncio.Future()

    agent.session.run = session
    await agent.start()
    runner = agent.process.runner
    await until(pid_file.exists, "the child's pid file")
    descendant = psutil.Process(int(pid_file.read_text()))
    if how == "cancel":
        runner.cancel()
    elif how == "stop":
        await agent.stop()
    await asyncio.gather(runner, return_exceptions=True)
    await until(lambda: not descendant.is_running() or descendant.status() == psutil.STATUS_ZOMBIE, "the child to end")
    assert agent.process.process is None and agent.session.task is None
    assert not agent.session.responses and not agent.session.accepts_updates
    assert route_lock_available(home), "retired process retained the route lock"
