"""The test template's own process: everything an app test imports is imported here once, the
comms observer's declarations included, and each test is a fork of it.

AppTestTemplate (support/template.py) starts this module in its own interpreter; the pytest
process that drives it never imports it, so its imports sit at the top of this file.
"""
from __future__ import annotations

from dataclasses import dataclass
import gc
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
from agent_comms.storage.typed_table import ProducedTable, TypedTable
from support.warm_helpers import HelperSpawner, WarmCoreConnection, WarmHelpers
from support.workspace import Workspace
from toad.file_kind import FileKind

PYTEST_OPTIONS = ("-p", "no:cacheprovider", "-q", "--no-header", "--tb=short", "--color=no")


@dataclass(frozen=True)
class TestProcess:
    """One test's process, as both of its forks become it: the test itself, and the spawner
    that forks its helpers (its route observer, its render workers). Each gets the test's
    files, environment and directory."""

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

    def run(self, spawner: socket.socket) -> None:
        """The test: run it with its helpers forked by the spawner, and never return."""
        code = 70
        try:
            self.become()
            WarmHelpers.spawner = spawner
            Workspace.local_connection = WarmCoreConnection
            sys.argv = ["pytest"]
            code = int(pytest.main([self.request["nodeid"], *PYTEST_OPTIONS]))
        except BaseException:
            traceback.print_exc()
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(code)

    def spawn_helpers(self, test: socket.socket) -> None:
        """The spawner: serve the test's helper requests until it exits, and never return."""
        code = 0
        try:
            self.become()
            HelperSpawner(test).serve()
        except BaseException:
            traceback.print_exc()
            code = 70
        finally:
            sys.stderr.flush()
            os._exit(code)


def serve() -> None:
    """Warm what every app test pays for, then fork each test and its helper spawner."""
    # Every agent_comms module once, so a forked helper imports and walks nothing.
    RootFile.load_declarations()
    # The file-preview terminal probe: 0.15 s of every app's start. Neither this process nor
    # a forked test has a terminal, so both detect the same answer.
    FileKind.prepare_terminal()
    # Each table's declared SQL is built once per process (0.74 s for all of them); every
    # test's stores compare against it, so the forks inherit it built.
    for table in TypedTable.members_with(TypedTable):
        table.schema_objects()
        table.schema_objects(if_not_exists=True)
    # A source checkout digests each producer from its parsed source when a bus installs its
    # schema: about 4 s of every test's store creation, the same answer every time.
    for produced in ProducedTable.members_with(ProducedTable):
        produced.producer_digest()
    # The warm heap is about 880,000 objects that no test frees. Frozen, a child's full
    # collection (pytest runs five at unconfigure) skips them: 0.23 s each becomes nothing.
    gc.freeze()
    if threading.active_count() != 1:
        raise RuntimeError(f"A fork must not inherit threads: {threading.enumerate()}")
    for line in sys.stdin.buffer:
        process = TestProcess(json.loads(line))
        sys.stdout.flush()
        sys.stderr.flush()
        test_end, spawner_end = socket.socketpair()
        if (spawner := os.fork()) == 0:
            test_end.close()
            process.spawn_helpers(spawner_end)
        spawner_end.close()
        if (pid := os.fork()) == 0:
            process.run(test_end)
        # The test holds the only other end: its exit is the spawner's end of input.
        test_end.close()
        reply({"pid": pid})
        _, status = os.waitpid(pid, 0)
        os.waitpid(spawner, 0)
        reply({"pid": pid, "exit_code": os.waitstatus_to_exitcode(status)})


def reply(fact: dict) -> None:
    sys.stdout.write(json.dumps(fact) + "\n")
    sys.stdout.flush()
