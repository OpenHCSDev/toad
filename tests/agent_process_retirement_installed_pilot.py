"""Installed ACP process retirement through EOF, cancellation and explicit stop."""
import asyncio
import fcntl
import os
from pathlib import Path
import shlex
import sys
import threading
from tempfile import TemporaryDirectory
from unittest.mock import patch
import psutil
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition


def publication_available():
    directory = Path.home() / ".local/state/agent-comms"
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    finally:
        os.close(descriptor)


async def cancelled_start(root):
    from toad.acp.maintenance_ingress import preflight

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def held_preflight(*args, **kwargs):
        entered.set()
        try:
            assert release.wait(5), "controlled preflight was not released"
            return preflight(*args, **kwargs)
        finally:
            finished.set()

    agent = Agent(root, AgentDefinition("cancelled-start", "Cancelled start", {"*": "true"}), None)
    with patch("toad.acp.maintenance_ingress.preflight", held_preflight):
        start = asyncio.create_task(agent.start())
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            assert not publication_available(), "start acquired no route custody"
            start.cancel()
            try:
                await start
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("cancelled start completed normally")
            assert agent.process.runner is None and agent.process.process is None
            assert publication_available(), "cancelled preflight leaked route custody"
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)
            await agent.stop()
    print("ACTUAL_CANCELLED_START_RELEASED_ROUTE_WITHOUT_CHILD", flush=True)


async def until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(.02)


async def case(root, mode):
    pid_file = root / f"{mode}.pid"
    code = (
        "import subprocess,sys,time;from pathlib import Path;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        f"Path({str(pid_file)!r}).write_text(str(p.pid));"
        + ("time.sleep(60)" if mode != "eof" else "")
    )
    command = shlex.join((sys.executable, "-c", code))
    agent = Agent(root, AgentDefinition("retirement", "Retirement", {"*": command}), None)
    async def session():
        await asyncio.Future()

    agent.session.run = session
    await agent.start()
    runner = agent.process.runner
    await until(pid_file.exists)
    descendant = psutil.Process(int(pid_file.read_text()))
    if mode == "cancel":
        runner.cancel()
    elif mode == "stop":
        await agent.stop()
    await asyncio.gather(runner, return_exceptions=True)
    await until(lambda: not descendant.is_running() or descendant.status() == psutil.STATUS_ZOMBIE)
    assert agent.process.process is None and agent.process.session_task is None
    assert not agent.process.responses and not agent.process.accepts_updates
    assert publication_available(), "retired process retained route custody"
    print(f"ACTUAL_{mode.upper()}_CHILD_AND_SESSION_RETIRED", flush=True)


async def main():
    artifacts = Path(__file__).resolve().parents[1] / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="process-retirement-", dir=artifacts) as directory:
        home = Path(directory)
        root = home / ".agent-comms"
        root.mkdir()
        with patch.dict(os.environ, {"HOME": str(home), "AGENT_COMMS_ROOT": str(root),
                                    "XDG_STATE_HOME": str(root / "state")}):
            await cancelled_start(root)
            for mode in ("cancel", "stop", "eof"):
                await case(root, mode)


if __name__ == "__main__":
    asyncio.run(main())
