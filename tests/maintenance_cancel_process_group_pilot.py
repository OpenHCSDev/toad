"""Disposable real shell+marker child cancellation; no provider or live Toad."""

import asyncio
import os
import shlex
import signal
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import psutil

from toad.acp.maintenance_ingress import admitted_spawn


async def main() -> None:
    if os.name != "posix":
        print("real process group pilot: POSIX only")
        return
    with TemporaryDirectory(prefix="toad-maintenance-descendant-") as directory:
        read_fd, write_fd = os.pipe()
        loop = asyncio.get_running_loop()
        child_ready: asyncio.Future[int] = loop.create_future()
        held = asyncio.Event()
        release = asyncio.Event()
        from agent_comms.child_process import AttachedChild
        actual = AttachedChild.start
        shell = None
        data = bytearray()

        def receive() -> None:
            data.extend(os.read(read_fd, 128))
            if b"\n" in data and not child_ready.done():
                child_ready.set_result(int(data.strip()))

        loop.add_reader(read_fd, receive)
        code = (
            f"import os,signal;os.write({write_fd},"
            f"str(os.getpid()).encode()+b'\\n');os.close({write_fd});signal.pause()"
        )
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)} & wait"

        async def delayed_actual(*args, **kwargs):
            nonlocal shell
            shell = await actual(*args, **kwargs)
            await child_ready
            held.set()
            await release.wait()
            return shell

        try:
            with patch.dict(os.environ, {"AGENT_COMMS_ROOT": directory}), patch(
                "agent_comms.child_process.AttachedChild.start", delayed_actual
            ):
                attempt = asyncio.create_task(
                    admitted_spawn(
                        command, pass_fds=(write_fd,),



                        cwd=directory, env=os.environ.copy(),
                    )
                )
                await asyncio.wait_for(held.wait(), timeout=5)
                child_pid = child_ready.result()
                attempt.cancel()
                await asyncio.sleep(0)
                attempt.cancel()
                release.set()
                try:
                    await asyncio.wait_for(attempt, timeout=8)
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("cancelled ACP shell was returned as accepted")
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
    print("real disposable ACP shell and descendant retired before cancelled admission: PASS")


if __name__ == "__main__":
    asyncio.run(main())
