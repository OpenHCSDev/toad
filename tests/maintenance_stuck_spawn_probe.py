"""Disposable fail-closed admission probe for an indefinitely stuck ACP spawn.

The fake create_subprocess_shell never executes a command; a second process
attempts the test-only maintenance transition. The parent kills both owned
process groups after proving there was no pause ACK while spawn remained stuck.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def worker(wire_root: Path, ready: Path) -> None:
    from toad.acp.maintenance_ingress import admitted_spawn

    async def fake_stuck_spawn(*_args, **_kwargs):
        ready.write_text("stuck inside admitted spawn; no native executed")
        time.sleep(3600)  # Simulates a blocking OS Popen on this disposable loop.

    async def run() -> None:
        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(wire_root)}), patch(
            "asyncio.create_subprocess_shell", fake_stuck_spawn
        ):
            await admitted_spawn("marker-only fake", cwd=str(wire_root), env=os.environ.copy())

    asyncio.run(run())


def pause(wire_root: Path, ack: Path) -> None:
    from agent_comms.maintenance_barrier import MaintenanceBarrier
    from maintenance_control_fixture import FixtureMaintenanceControl

    FixtureMaintenanceControl(MaintenanceBarrier(wire_root / "registry.json")).begin("disposable")
    ack.write_text("pause acknowledged")


def parent(toad_src: Path, core_src: Path, core_tests: Path) -> None:
    with TemporaryDirectory(prefix="toad-stuck-spawn-") as directory:
        root = Path(directory)
        wire = root / "wire"
        ready = root / "spawn-stuck"
        ack = root / "pause-ack"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(map(str, (core_tests, core_src, toad_src)))
        worker_process = subprocess.Popen(
            [sys.executable, __file__, "--worker", str(wire), str(ready)],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        pause_process = None
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                if worker_process.poll() is not None:
                    raise RuntimeError("stuck-spawn fixture exited unexpectedly")
                time.sleep(0.01)
            assert ready.exists(), "fake OS spawn did not enter while gate held"
            pause_process = subprocess.Popen(
                [sys.executable, __file__, "--pause", str(wire), str(ack)],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
            time.sleep(0.25)
            assert worker_process.poll() is None
            assert pause_process.poll() is None
            assert not ack.exists(), "maintenance pause ACKed with unknown spawn in flight"
            print("PASS: stuck fake OS spawn holds admission; pause has no early ACK")
            print("BLOCKER: no bounded stuck-spawn retirement or provider-child proof")
        finally:
            for process in (pause_process, worker_process):
                if process is None:
                    continue
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", nargs=2, type=Path)
    parser.add_argument("--pause", nargs=2, type=Path)
    parser.add_argument("--toad-src", type=Path)
    parser.add_argument("--core-src", type=Path)
    parser.add_argument("--core-tests", type=Path)
    arguments = parser.parse_args()
    if arguments.worker:
        worker(*arguments.worker)
    elif arguments.pause:
        pause(*arguments.pause)
    else:
        if not all((arguments.toad_src, arguments.core_src, arguments.core_tests)):
            parser.error("--toad-src, --core-src, and --core-tests are required")
        parent(arguments.toad_src, arguments.core_src, arguments.core_tests)
