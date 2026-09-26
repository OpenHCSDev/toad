"""Disposable Linux PID-namespace containment probe; NEVER touches a live Toad process.

A namespace PID1 forks a marker-only setsid child. The parent verifies separate
namespace/PID1, then kills only its owned PID1 and observes both pidfds exit.
"""

from __future__ import annotations

import argparse
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


def children_of(pid: int) -> list[int]:
    raw = Path(f"/proc/{pid}/task/{pid}/children").read_text().strip()
    return [int(value) for value in raw.split()] if raw else []


def wait_for_child(pid: int, *, timeout: float = 5.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            children = children_of(pid)
        except FileNotFoundError:
            break
        if children:
            return children[0]
        time.sleep(0.01)
    raise RuntimeError(f"no child under owned pid {pid}")


def child(ready: Path) -> None:
    if os.getpid() != 1:
        raise RuntimeError("namespace fixture is not PID1")
    descendant = os.fork()
    if descendant == 0:
        os.setsid()
        signal.pause()
        os._exit(0)
    ready.write_text(str(descendant))
    signal.pause()


def parent(unshare_binary: str = "unshare") -> None:
    if sys.platform != "linux" or not hasattr(os, "pidfd_open"):
        print("BLOCKED: Linux pidfd and user/pid namespace required")
        return
    with TemporaryDirectory(prefix="toad-namespace-retirement-") as directory:
        ready = Path(directory) / "ready"
        command = [
            unshare_binary, "--user", "--map-root-user", "--pid", "--fork", "--mount-proc",
            sys.executable, __file__, "--child", str(ready),
        ]
        intermediary = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
        )
        init_pid = escaped_pid = -1
        init_fd = escaped_fd = -1
        try:
            try:
                init_pid = wait_for_child(intermediary.pid)
            except RuntimeError:
                if intermediary.poll() is not None:
                    _, error = intermediary.communicate(timeout=5)
                    print(f"BLOCKED: unshare failed before PID1: {error.decode(errors='replace').strip()}")
                    return
                raise
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not ready.exists():
                raise RuntimeError("namespace PID1 failed to declare readiness")
            escaped_pid = wait_for_child(init_pid)
            assert int(ready.read_text()) == 2, "setsid child not PID2 inside namespace"
            host_ns = os.stat("/proc/self/ns/pid").st_ino
            init_ns = os.stat(f"/proc/{init_pid}/ns/pid").st_ino
            escaped_ns = os.stat(f"/proc/{escaped_pid}/ns/pid").st_ino
            assert init_ns == escaped_ns and init_ns != host_ns
            init_fd = os.pidfd_open(init_pid)
            escaped_fd = os.pidfd_open(escaped_pid)
            assert os.getpgid(escaped_pid) != os.getpgid(init_pid), "fixture did not escape shell group"
            os.kill(init_pid, signal.SIGKILL)
            poll = select.poll()
            poll.register(init_fd, select.POLLIN)
            poll.register(escaped_fd, select.POLLIN)
            seen: set[int] = set()
            deadline = time.monotonic() + 5
            while len(seen) < 2 and time.monotonic() < deadline:
                for fd, _ in poll.poll(100):
                    seen.add(fd)
            assert {init_fd, escaped_fd} <= seen, "PID1 or escaped child did not exit"
            print("PASS: distinct PID namespace PID1 kill retires marker-only setsid descendant pidfd")
        finally:
            if init_fd >= 0:
                os.close(init_fd)
            if escaped_fd >= 0:
                os.close(escaped_fd)
            for pid in (escaped_pid, init_pid):
                if pid > 0:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            if intermediary.poll() is None:
                intermediary.kill()
            try:
                intermediary.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                intermediary.kill()
                intermediary.communicate(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", type=Path)
    parser.add_argument("--unshare", default="unshare")
    arguments = parser.parse_args()
    if arguments.child is None:
        parent(arguments.unshare)
    else:
        child(arguments.child)
