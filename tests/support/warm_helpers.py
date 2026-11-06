"""Every helper an app test starts (its route observer, its render workers) forked warm from
the test template instead of spawned cold.

The application spawns each helper (HelperStart, agent_comms.child_process): a fresh
interpreter that imports the observer's or the renderer's whole module graph again, about
two seconds a process. The template has already imported all of it, so beside each test it
forks a HelperSpawner that has become that test's process. A helper keeps multiprocessing's
spawn protocol whole (the same preparation data and pickled process object on the same
pipe, its descriptors at the same numbers); only the new interpreter is replaced by a fork
of the warm one.
"""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import io
from multiprocessing import popen_spawn_posix, reduction, resource_tracker, spawn, util
from multiprocessing.context import SpawnContext, SpawnProcess, set_spawning_popen
import os
import pickle
import select
import socket
import struct
from typing import ClassVar

from agent_comms.child_process import HelperStart
from toad.comms_root import LocalCoreConnection

EXIT = struct.Struct("i")


class WarmHelpers(HelperStart):
    """A test forked by the template: its spawner sits at the other end of ``spawner``, set
    when the fork becomes the test."""

    spawner: ClassVar[socket.socket]

    def context(self) -> WarmContext:
        return WarmContext()

    @classmethod
    def request(cls, fds: list[int], status: int, *, tracker: int, pipe: int) -> None:
        """One helper whose descriptors are ``fds`` at these numbers; ``status`` hears its
        pid, then its exit code."""
        message = pickle.dumps((fds, tracker, pipe))
        socket.send_fds(cls.spawner, [message], [*fds, status])


class WarmPopen(popen_spawn_posix.Popen):
    """spawn's launch, with the interpreter replaced by a fork of the warm spawner. The helper
    is the spawner's child, so its exit code arrives on a status pipe instead of waitpid."""

    def _launch(self, process_obj: SpawnProcess) -> None:
        tracker = resource_tracker.getfd()
        self._fds.append(tracker)
        data = io.BytesIO()
        set_spawning_popen(self)
        try:
            reduction.dump(spawn.get_preparation_data(process_obj._name), data)
            reduction.dump(process_obj, data)
        finally:
            set_spawning_popen(None)
        parent_r, child_w = os.pipe()
        child_r, parent_w = os.pipe()
        self.status, status_w = os.pipe()
        self._fds.extend([child_r, child_w])
        WarmHelpers.request(self._fds, status_w, tracker=tracker, pipe=child_r)
        for fd in (child_r, child_w, status_w):
            os.close(fd)
        self.pid = EXIT.unpack(os.read(self.status, EXIT.size))[0]
        self.sentinel = parent_r
        with open(parent_w, "wb", closefd=False) as pipe:
            pipe.write(data.getbuffer())
        self.finalizer = util.Finalize(self, util.close_fds, [parent_r, parent_w, self.status])

    def poll(self, flag: int = os.WNOHANG) -> int | None:
        if self.returncode is None:
            if flag == os.WNOHANG and not select.select([self.status], [], [], 0)[0]:
                return None
            self.returncode = EXIT.unpack(os.read(self.status, EXIT.size))[0]
        return self.returncode


@dataclass(frozen=True)
class WarmCoreConnection(LocalCoreConnection):
    """The workspace's local Core, whose helpers fork from the warm template."""

    helper_start: ClassVar[HelperStart] = WarmHelpers()


class WarmProcess(SpawnProcess):
    @staticmethod
    def _Popen(process_obj: SpawnProcess) -> WarmPopen:
        return WarmPopen(process_obj)


class WarmContext(SpawnContext):
    Process = WarmProcess


@dataclass(frozen=True)
class HelperSpawner:
    """Forked from the template beside one test, after becoming that test's process: forks
    one helper per request until the test closes its end, then reaps them."""

    test: socket.socket

    def serve(self) -> None:
        while request := self.receive():
            (numbers, tracker, pipe), fds = request
            if os.fork() == 0:
                self.test.close()
                self.watch(numbers, fds, tracker=tracker, pipe=pipe)
            for fd in fds:
                os.close(fd)
            self.reap(os.WNOHANG)
        self.reap(0)

    def receive(self) -> tuple[tuple[list[int], int, int], list[int]] | None:
        data, fds, _, _ = socket.recv_fds(self.test, 1 << 16, 64)
        return (pickle.loads(data), fds) if data else None

    @staticmethod
    def watch(numbers: list[int], fds: list[int], *, tracker: int, pipe: int) -> None:
        """Fork the helper, report its pid and then its exit code, and never return."""
        *received, status = fds
        if (helper := os.fork()) == 0:
            os.close(status)
            HelperSpawner.become_helper(numbers, received, tracker=tracker, pipe=pipe)
        for fd in received:
            os.close(fd)
        os.write(status, EXIT.pack(helper))
        _, code = os.waitpid(helper, 0)
        os.write(status, EXIT.pack(os.waitstatus_to_exitcode(code)))
        os._exit(0)

    @staticmethod
    def become_helper(numbers: list[int], received: list[int], *, tracker: int, pipe: int) -> None:
        """Put each descriptor at the number the pickled process names, then run spawn's
        child half (multiprocessing.spawn.spawn_main) in this warm interpreter."""
        moved = [fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 1024) for fd in received]
        for fd in received:
            os.close(fd)
        for fd, number in zip(moved, numbers):
            os.dup2(fd, number, inheritable=False)
            os.close(fd)
        resource_tracker._resource_tracker._fd = tracker
        os._exit(spawn._main(pipe, os.dup(pipe)))

    @staticmethod
    def reap(flag: int) -> None:
        while True:
            try:
                pid, _ = os.waitpid(-1, flag)
            except ChildProcessError:
                return
            if pid == 0:
                return
