"""Installed ACP process retirement through EOF, cancellation and explicit stop."""
import asyncio
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
import psutil
from toad.acp.agent import Agent


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
    agent = Agent(root, {"name": "retirement", "run_command": {"*": command}}, None)
    agent.post_message = lambda message: None
    session_cancelled = asyncio.Event()

    async def session():
        try:
            await asyncio.Future()
        finally:
            session_cancelled.set()

    agent.run = session
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
    assert session_cancelled.is_set()
    assert agent.process.process is None and agent.process.session_task is None
    assert not agent.process.responses and not agent.process.accepts_updates
    print(f"ACTUAL_{mode.upper()}_CHILD_AND_SESSION_RETIRED", flush=True)


async def main():
    with TemporaryDirectory(prefix="process-retirement-") as directory:
        root = Path(directory)
        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(root),
                                    "XDG_STATE_HOME": str(root / "state")}):
            for mode in ("cancel", "stop", "eof"):
                await case(root, mode)


if __name__ == "__main__":
    asyncio.run(main())
