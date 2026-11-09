"""Stopping what a test left running."""

from __future__ import annotations

import asyncio

import psutil
from agent_comms.execution.child_process import STOP_GRACE_SECONDS

from support.roots import ATTEMPT


async def stop_test_children(attempt: str, began: float) -> None:
    """Stop every process started under one test's roots (never this runner or its ancestors).

    A process's environment is fixed at birth, so only one born after the test began can carry
    its attempt; the environ of every older process on the host is never read."""
    runner = psutil.Process()
    ancestors = {process.pid for process in runner.parents()}
    for process in psutil.process_iter(["create_time"]):
        if process.info["create_time"] < began:
            continue
        try:
            if (process.pid == runner.pid or process.pid in ancestors
                    or process.environ().get(ATTEMPT) != attempt):
                continue
            process.terminate()
            try:
                async with asyncio.timeout(STOP_GRACE_SECONDS):
                    while process.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                        await asyncio.sleep(.02)
            except TimeoutError:
                process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            continue
