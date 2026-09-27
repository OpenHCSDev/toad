"""Toad-side admission for a prospective, default-off Comms maintenance barrier.

This only constrains Toad processes importing this code. Old clients need external
exclusion before any maintenance window can be declared safe.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import signal
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping


_pending_spawns = 0


def configured_root(env: Mapping[str, str], cwd: str | Path) -> Path:
    """Resolve the child wire; never mistake the parent's route for another HOME."""
    if "AGENT_COMMS_ROOT" not in env:
        home_key = "USERPROFILE" if os.name == "nt" else "HOME"
        home = env.get(home_key)
        if (not home or not Path(home).is_absolute()
                or home != str(Path.home())
                or "AGENT_COMMS_ROOT" in os.environ):
            raise ValueError(
                "ACP default route requires the Toad process HOME and no parent "
                "root override; set an explicit child AGENT_COMMS_ROOT"
            )
        from toad.comms_root import current_root

        return current_root()
    text = env["AGENT_COMMS_ROOT"]
    if text == "~" or text.startswith("~/"):
        home = env.get("HOME") if os.name != "nt" else env.get("USERPROFILE")
        if not home or not Path(home).is_absolute():
            raise ValueError("ACP home for maintenance admission is unknown")
        text = str(Path(home) / text[2:]) if text != "~" else home
    elif text.startswith("~"):
        raise ValueError("Unsupported ACP home expansion during maintenance admission")
    raw = Path(text)
    return (raw if raw.is_absolute() else Path(cwd) / raw).resolve()


def barrier_for(root: str | Path | None = None, *, cwd: str | Path | None = None) -> Any:
    """Use the paired Comms barrier; never silently skip a missing package."""
    from agent_comms.maintenance_barrier import MaintenanceBarrier

    resolved = Path(root) if root is not None else configured_root(os.environ, cwd or os.getcwd())
    resolved = resolved.expanduser()
    if not resolved.is_absolute():
        resolved = Path(cwd or os.getcwd()) / resolved
    return MaintenanceBarrier(resolved.resolve() / "registry.json")


@contextmanager
def admission(
    root: str | None = None, *, ingress_root: str | Path | None = None,
    cwd: str | Path | None = None,
) -> Iterator[None]:
    """Guard both the default ingress and any attached non-default wire root.

    ACP metadata may name a second root. It cannot redirect admission away from
    the default Toad ingress root; deterministic lock order avoids cross-root
    deadlock with other Toad attachments.
    """
    configured = barrier_for(ingress_root, cwd=cwd)
    attached = barrier_for(root, cwd=cwd) if root is not None else configured
    paths = {configured.registry_path, attached.registry_path}
    with ExitStack() as stack:
        for path in sorted(paths):
            stack.enter_context(barrier_for(str(path.parent)).admit_ingress())
        yield


def preflight(
    root: str | None = None, *, ingress_root: str | Path | None = None,
    cwd: str | Path | None = None,
) -> None:
    """Early denial only: the later spawn/send holds the actual wire lock."""
    with admission(root, ingress_root=ingress_root, cwd=cwd):
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
    child_env = (kwargs["env"] if kwargs.get("env") is not None else os.environ).copy()
    child_cwd = str(Path(kwargs["cwd"] if kwargs.get("cwd") is not None else os.getcwd()).resolve())
    ingress_root = configured_root(child_env, child_cwd)
    from toad.comms_root import implicit_root, selected_write

    # The child env is pinned explicitly below, but its parent may have
    # selected that root through the default route. Preserve that distinction.
    default_route = implicit_root()
    # The gate and child must use the *same* target even if an alias symlink
    # changes after admission but before exec. Never inherit a relative root.
    child_env["AGENT_COMMS_ROOT"] = str(ingress_root)
    kwargs["env"] = child_env
    kwargs["cwd"] = child_cwd
    process_ready: concurrent.futures.Future[asyncio.subprocess.Process] = concurrent.futures.Future()
    decision: concurrent.futures.Future[bool] = concurrent.futures.Future()

    global _pending_spawns
    _pending_spawns += 1

    async def settle(task: asyncio.Future[Any]) -> tuple[Any, bool]:
        """Repeated caller cancellation cannot abandon a lock-held spawn."""
        cancelled = False
        while True:
            try:
                return await asyncio.shield(task), cancelled
            except asyncio.CancelledError:
                cancelled = True

    def live_group_members(group: int) -> bool:
        """A zombie is exited, but an orphaned running member is not retired."""
        import psutil

        for member in psutil.process_iter():
            try:
                if os.getpgid(member.pid) == group and member.status() != psutil.STATUS_ZOMBIE:
                    return True
            except (ProcessLookupError, psutil.NoSuchProcess):
                continue
        return False

    async def retire(process: asyncio.subprocess.Process) -> None:
        group = process.pid if os.name != "nt" and kwargs.get("start_new_session") else None
        if process.returncode is None:
            try:
                if group is not None:
                    os.killpg(group, signal.SIGTERM)
                else:
                    process.terminate()
            except ProcessLookupError:
                pass
            wait = asyncio.create_task(asyncio.wait_for(process.wait(), timeout=2))
            try:
                await settle(wait)
            except TimeoutError:
                try:
                    if group is not None:
                        os.killpg(group, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                await settle(asyncio.create_task(process.wait()))
        if group is not None:
            # Shell wait alone does not prove its marker-only ACP descendants
            # stopped. Keep the wire lock until every same-group live member
            # exits. An unkillable member conservatively stalls the pause.
            escalation = time.monotonic() + 0.2
            while await asyncio.to_thread(live_group_members, group):
                if time.monotonic() >= escalation:
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                await asyncio.sleep(0.02)

    def spawn_under_lock() -> None:
        try:
            # Route SH precedes the maintenance/bus lock, matching the core
            # publisher's route EX -> private-root preflight ordering. Hold it
            # through the actual spawn and settlement, not just UI preflight.
            with selected_write(ingress_root, implicit=default_route), admission(
                root, ingress_root=ingress_root, cwd=child_cwd
            ):
                future = asyncio.run_coroutine_threadsafe(
                    asyncio.create_subprocess_shell(command, **kwargs), loop
                )
                process = future.result()
                process_ready.set_result(process)
                # The caller must accept the observed process or ask for
                # retirement before releasing the lock to a maintenance pause.
                if not decision.result():
                    while True:
                        try:
                            asyncio.run_coroutine_threadsafe(retire(process), loop).result()
                        except Exception:
                            # If inspection/retirement is uncertain, do not
                            # release the wire lock and certify a safe pause.
                            # An operator must retire this old-capable client
                            # externally; retry only the same child's cleanup.
                            time.sleep(0.1)
                            continue
                        break
        except BaseException as error:
            if not process_ready.done():
                process_ready.set_exception(error)
            else:
                raise

    worker = asyncio.create_task(asyncio.to_thread(spawn_under_lock))
    try:
        try:
            process, cancelled = await settle(asyncio.wrap_future(process_ready))
        except BaseException:
            await settle(worker)
            raise
        if cancelled:
            decision.set_result(False)
            await settle(worker)
            raise asyncio.CancelledError
        decision.set_result(True)
        # No await between acceptance and returning ownership to Agent._run_agent.
        return process
    finally:
        _pending_spawns -= 1


@contextmanager
def admitted_prompt(
    root: str | None = None, *, ingress_root: str | Path | None = None,
    cwd: str | Path | None = None,
) -> Iterator[None]:
    """Guard synchronous JSONRPC enqueue through its stdin.write boundary.

    Never synchronously wait for a wire lock held by this event loop's own
    pending async spawn (whose worker needs the loop to finish the spawn).
    Decline instead; Toad restores an unaccepted user prompt for later choice.
    """
    if _pending_spawns:
        raise ValueError("ACP spawn admission is in progress; prompt not sent")
    from toad.comms_root import implicit_root, selected_write

    selected = Path(ingress_root) if ingress_root is not None else configured_root(
        os.environ, cwd or os.getcwd()
    )
    with selected_write(selected, implicit=implicit_root()), admission(
        root, ingress_root=selected, cwd=cwd
    ):
        yield
