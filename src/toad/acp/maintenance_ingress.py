"""Toad-side admission for a prospective, default-off Comms maintenance barrier.

This only constrains Toad processes importing this code. Old clients need external
exclusion before any maintenance window can be declared safe.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterator


_pending_spawns = 0


def barrier_for(root: str | None = None) -> Any:
    """Use the paired Comms barrier; never silently skip a missing package."""
    from agent_comms.maintenance_barrier import MaintenanceBarrier

    resolved = Path(root or os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms"))
    return MaintenanceBarrier(resolved.expanduser().resolve() / "registry.json")


@contextmanager
def admission(root: str | None = None) -> Iterator[None]:
    """Guard both the default ingress and any attached non-default wire root.

    ACP metadata may name a second root. It cannot redirect admission away from
    the default Toad ingress root; deterministic lock order avoids cross-root
    deadlock with other Toad attachments.
    """
    configured = barrier_for()
    attached = barrier_for(root)
    paths = {configured.registry_path, attached.registry_path}
    with ExitStack() as stack:
        for path in sorted(paths):
            stack.enter_context(barrier_for(str(path.parent)).admit_ingress())
        yield


def preflight(root: str | None = None) -> None:
    """Early denial only: the later spawn/send holds the actual wire lock."""
    with admission(root):
        pass


async def admitted_spawn(command: str, *, root: str | None = None, **kwargs: Any) -> asyncio.subprocess.Process:
    """Hold the core wire lock until the asynchronous ACP spawn settles.

    Acquiring a process lock on the Toad event loop can deadlock if another task
    is spawning. A worker owns the *synchronous* core admission context while
    scheduling the actual asyncio subprocess on the original event loop. A
    cancelled caller still waits for the exact spawn and retires its child;
    it never drops the gate lock while an unobserved spawn can complete later.
    A permanently stuck OS spawn can prevent maintenance pause from completing:
    this helper does not purport to provide a bounded retirement deadline.
    """
    loop = asyncio.get_running_loop()
    def spawn_under_lock() -> asyncio.subprocess.Process:
        with admission(root):
            future = asyncio.run_coroutine_threadsafe(
                asyncio.create_subprocess_shell(command, **kwargs), loop
            )
            return future.result()

    global _pending_spawns
    _pending_spawns += 1
    task = asyncio.create_task(asyncio.to_thread(spawn_under_lock))
    try:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Do not abandon an in-flight spawn or a lock-holding worker thread.
            process = await asyncio.shield(task)
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                await process.wait()
            raise
    finally:
        _pending_spawns -= 1


@contextmanager
def admitted_prompt(root: str | None = None) -> Iterator[None]:
    """Guard synchronous JSONRPC enqueue through its stdin.write boundary.

    Never synchronously wait for a wire lock held by this event loop's own
    pending async spawn (whose worker needs the loop to finish the spawn).
    Decline instead; Toad restores an unaccepted user prompt for later choice.
    """
    if _pending_spawns:
        raise ValueError("ACP spawn admission is in progress; prompt not sent")
    with admission(root):
        yield
