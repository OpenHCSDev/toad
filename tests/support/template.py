"""One interpreter that imports the app once and forks a fresh process for each app test.

Importing Toad, Textual and agent-comms is about half of an app test's boot. Nothing they
read at import varies between tests (the roots' TERM, COLORTERM and FORCE_COLOR are the
same for every test), and none of them starts a thread or a loop on import, so a fork
taken after the imports is as fresh as a new interpreter for everything a test owns:
render workers, the comms route, settings paths and the heap freeze all start with the
app inside the child.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time

from support.roots import Roots

@dataclass(frozen=True)
class ForkedRun:
    """What one forked test process left: its exit code, or none when it ran out its time."""

    exit_code: int | None
    stdout: bytes
    stderr: bytes

    @property
    def successful(self) -> bool:
        return self.exit_code == 0

    def __repr__(self) -> str:
        return "timed out" if self.exit_code is None else f"exit code {self.exit_code}"


class AppTestTemplate:
    """The imported interpreter this runner forks its app tests from."""

    def __init__(self, rootpath: Path) -> None:
        self.roots = Roots.create()
        self.rootpath = rootpath
        self.log = self.roots.attempt / "template-stderr.log"
        tests = Path(__file__).resolve().parents[1]
        self.process = subprocess.Popen(
            (sys.executable, "-c",
             f"import sys; sys.path[:0] = [{str(tests)!r}, {str(rootpath / 'src')!r}]; "
             "from support.template_server import serve; serve()"),
            cwd=rootpath, env=self.roots.environment(dict(os.environ)),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log.open("wb"),
            # Unbuffered: each reply is read only after select sees it, so a fast test's
            # pid and exit replies can never sit unseen together in a Python buffer.
            bufsize=0)

    def run(self, nodeid: str, *, env: dict[str, str], attempt: Path, timeout: float) -> ForkedRun:
        stdout, stderr = attempt / "stdout.log", attempt / "stderr.log"
        request = {"nodeid": nodeid, "env": env, "cwd": str(self.rootpath),
                   "stdout": str(stdout), "stderr": str(stderr)}
        assert self.process.stdin is not None
        self.process.stdin.write((json.dumps(request) + "\n").encode())
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        pid = self.reply(deadline)["pid"]
        try:
            exit_code = self.reply(deadline)["exit_code"]
        except TimeoutError:
            os.kill(pid, signal.SIGKILL)
            self.reply(time.monotonic() + 30)
            exit_code = None
        return ForkedRun(exit_code, stdout.read_bytes(), stderr.read_bytes())

    def reply(self, deadline: float) -> dict:
        assert self.process.stdout is not None
        ready, _, _ = select.select([self.process.stdout], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            raise TimeoutError
        if not (line := self.process.stdout.readline()):
            raise RuntimeError(f"The test template exited: {self.log.read_text(errors='replace')[-4000:]}")
        return json.loads(line)

    def stop(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        self.process.wait(timeout=30)
        shutil.rmtree(self.roots.attempt)
