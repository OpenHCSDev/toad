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


def pidfd_exited(fd: int) -> bool:
    return bool(select.select([fd], [], [], 0)[0])


def retire_exact_pidfd(fd: int) -> None:
    """Never signal a saved numeric PID after its target can have exited."""
    if not pidfd_exited(fd):
        try:
            signal.pidfd_send_signal(fd, signal.SIGKILL)
        except ProcessLookupError:
            pass


def adopt_init_pidfd(intermediary_pid: int, init_pid: int) -> tuple[int, int]:
    """Pin the live intermediary child and its namespace before reading descendants."""
    fd = os.pidfd_open(init_pid)
    ns_fd = -1
    try:
        if pidfd_exited(fd):
            raise RuntimeError("namespace PID1 exited before acquisition")
        ns_fd = os.open(f"/proc/{init_pid}/ns/pid", os.O_RDONLY)
        ns_inode = os.fstat(ns_fd).st_ino
        if ns_inode == os.stat("/proc/self/ns/pid").st_ino:
            raise RuntimeError("namespace PID1 is in host namespace")
        if init_pid not in children_of(intermediary_pid) or pidfd_exited(fd):
            raise RuntimeError("namespace PID1 is no longer an owned live child")
        return fd, ns_fd
    except BaseException:
        if ns_fd >= 0:
            os.close(ns_fd)
        os.close(fd)
        raise


def adopt_escaped_pidfd(init_pid: int, init_fd: int, ns_fd: int, escaped_pid: int) -> int:
    """Reject recycled numeric parent/child identities before arming cleanup."""
    if pidfd_exited(init_fd):
        raise RuntimeError("namespace PID1 exited before descendant acquisition")
    fd = os.pidfd_open(escaped_pid)
    try:
        if pidfd_exited(init_fd):
            raise RuntimeError("namespace PID1 exited during descendant acquisition")
        if os.stat(f"/proc/{escaped_pid}/ns/pid").st_ino != os.fstat(ns_fd).st_ino:
            raise RuntimeError("descendant is not in pinned PID namespace")
        if escaped_pid not in children_of(init_pid):
            raise RuntimeError("descendant is not a child of pinned PID1")
        if pidfd_exited(init_fd) or pidfd_exited(fd):
            raise RuntimeError("PID1 or descendant exited during validation")
        return fd
    except BaseException:
        os.close(fd)  # Unvalidated target: never signal it.
        raise


def child(ready: Path) -> None:
    if os.getpid() != 1:
        raise RuntimeError("namespace fixture is not PID1")
    descendant = os.fork()
    if descendant == 0:
        os.setsid()
        ready.with_suffix(".setsid").write_text(str(os.getpid()))
        signal.pause()
        os._exit(0)
    ready.write_text(str(descendant))
    signal.pause()


def parent(unshare_binary: str = "unshare") -> None:
    if sys.platform != "linux" or not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        print(f"BLOCKED: PID namespace and Python pidfd APIs required in {sys.executable} ({sys.version.split()[0]})")
        return
    with TemporaryDirectory(prefix="toad-namespace-retirement-") as directory:
        ready = Path(directory) / "ready"
        command = [
            unshare_binary, "--user", "--map-root-user", "--pid", "--fork", "--kill-child", "--mount-proc",
            sys.executable, __file__, "--child", str(ready),
        ]
        intermediary = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
        )
        init_pid = escaped_pid = -1
        init_fd = escaped_fd = ns_fd = -1
        try:
            try:
                init_pid = wait_for_child(intermediary.pid)
            except RuntimeError:
                if intermediary.poll() is not None:
                    _, error = intermediary.communicate(timeout=5)
                    print(f"BLOCKED: unshare failed before PID1: {error.decode(errors='replace').strip()}")
                    return
                raise
            init_fd, ns_fd = adopt_init_pidfd(intermediary.pid, init_pid)
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not ready.exists():
                raise RuntimeError("namespace PID1 failed to declare readiness")
            escaped_pid = wait_for_child(init_pid)
            setsid_ready = ready.with_suffix(".setsid")
            deadline = time.monotonic() + 5
            while not setsid_ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not setsid_ready.exists():
                raise RuntimeError("escaped child did not finish setsid")
            assert int(ready.read_text()) == 2 == int(setsid_ready.read_text()), "setsid child not PID2 inside namespace"
            escaped_fd = adopt_escaped_pidfd(init_pid, init_fd, ns_fd, escaped_pid)
            assert os.getpgid(escaped_pid) != os.getpgid(init_pid), "fixture did not escape shell group"
            signal.pidfd_send_signal(init_fd, signal.SIGKILL)
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
            # The still-owned intermediary has --kill-child as a fallback if
            # PID1 was never verified/opened. Do not kill saved numeric PIDs.
            if intermediary.poll() is None:
                intermediary.kill()
            for fd in (init_fd, escaped_fd):
                if fd >= 0:
                    retire_exact_pidfd(fd)
                    os.close(fd)
            if ns_fd >= 0:
                os.close(ns_fd)
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
