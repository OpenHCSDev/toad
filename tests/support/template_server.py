"""The test template's own process: everything an app test imports is imported here once, the
comms observer's declarations included, and each test is a fork of it.

AppTestTemplate (support/template.py) starts this module in its own interpreter; the pytest
process that drives it never imports it, so its imports sit at the top of this file.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import socket
import sys
import tempfile
import threading
import traceback

import pytest

import support.workspace  # noqa: F401  (the app, its fixtures and the comms package)
from agent_comms.storage.locked_store import RootFile
from support.template_observation import ForkedObservers, ObserverChannel, ObserverSpawner

PYTEST_OPTIONS = ("-p", "no:cacheprovider", "-q", "--no-header", "--tb=short", "--color=no")


@dataclass(frozen=True)
class TestProcess:
    """One test's process, as both of its forks become it: the test itself, and the spawner
    that forks its observers. Each gets the test's files, environment and directory."""

    request: dict

    def become(self) -> None:
        # The request pipe and the reply pipe are the template's; the test gets its own files.
        null = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null, 0)
        os.close(null)
        for fd, path in ((1, self.request["stdout"]), (2, self.request["stderr"])):
            target = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.dup2(target, fd)
            os.close(target)
        os.environ.clear()
        os.environ.update(self.request["env"])
        # tempfile keeps the first directory it resolved; this test's TMPDIR is a new one.
        tempfile.tempdir = None
        os.chdir(self.request["cwd"])

    def run(self, observers: ForkedObservers) -> None:
        """The test: run it with its observers forked by the spawner, and never return."""
        code = 70
        try:
            self.become()
            ObserverChannel.current = observers
            sys.argv = ["pytest"]
            code = int(pytest.main([self.request["nodeid"], *PYTEST_OPTIONS]))
        except BaseException:
            traceback.print_exc()
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(code)

    def spawn_observers(self, test: socket.socket) -> None:
        """The spawner: serve the test's observer requests until it exits, and never return."""
        code = 0
        try:
            self.become()
            ObserverSpawner(test).serve()
        except BaseException:
            traceback.print_exc()
            code = 70
        finally:
            sys.stderr.flush()
            os._exit(code)


def serve() -> None:
    """Warm what every app test pays for, then fork each test and its observer spawner."""
    # Every agent_comms module once, so a forked observer's declarations_in walks nothing.
    RootFile.load_declarations()
    if threading.active_count() != 1:
        raise RuntimeError(f"A fork must not inherit threads: {threading.enumerate()}")
    for line in sys.stdin.buffer:
        process = TestProcess(json.loads(line))
        sys.stdout.flush()
        sys.stderr.flush()
        test_end, spawner_end = socket.socketpair()
        if (spawner := os.fork()) == 0:
            test_end.close()
            process.spawn_observers(spawner_end)
        spawner_end.close()
        if (pid := os.fork()) == 0:
            process.run(ForkedObservers(test_end))
        # The test holds the only other end: its exit is the spawner's end of input.
        test_end.close()
        reply({"pid": pid})
        _, status = os.waitpid(pid, 0)
        os.waitpid(spawner, 0)
        reply({"pid": pid, "exit_code": os.waitstatus_to_exitcode(status)})


def reply(fact: dict) -> None:
    sys.stdout.write(json.dumps(fact) + "\n")
    sys.stdout.flush()
