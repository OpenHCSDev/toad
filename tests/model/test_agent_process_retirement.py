"""An agent process ends through EOF, cancellation or an explicit stop with its child gone and its session retired."""

import asyncio
import sys

import psutil
import pytest

from support.agents import command
from toad.acp.agent import Agent


@pytest.fixture
def home(tmp_path, monkeypatch):
    """The user's home is private to this test."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


async def until(ui_condition, why):
    try:
        async with asyncio.timeout(8):
            while not ui_condition():
                await asyncio.sleep(.02)
    except TimeoutError:
        raise AssertionError(f"{why} not reached in 8s") from None


@pytest.mark.parametrize("how", ["cancel", "stop", "eof"])
async def test_the_child_and_session_are_retired(home, how, app_agents):
    pid_file = home / f"{how}.pid"
    code = (
        "import subprocess,sys,time;from pathlib import Path;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        f"Path({str(pid_file)!r}).write_text(str(p.pid));"
        + ("time.sleep(60)" if how != "eof" else "")
    )
    agent = app_agents.agent(
        Agent, command(sys.executable, "-c", code, name="Retirement", identity="retirement"),
    )

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
