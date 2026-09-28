"""Collect script pilots once, using the installed pinned stack and bounded children."""

import ast
import asyncio
import os
from pathlib import Path
import sys

import pytest
import psutil
from agent_comms.child_process import BoundedRun, DetachedProcess, ProcessIdentity


def pytest_addoption(parser):
    parser.addoption('--pilot-timeout', type=float, default=90,
                     help='One attempt per pilot, bounded wall seconds (no retries)')


class PilotFile(pytest.File):
    def collect(self):
        if self.path.stem.endswith(("_fixture", "_app", "_probe")):
            return
        tree = ast.parse(self.path.read_text())
        if any(isinstance(node, ast.If) and ast.unparse(node.test) == "__name__ == '__main__'"
               for node in tree.body):
            yield Pilot.from_parent(self, name=self.path.stem)


class Pilot(pytest.Item):
    def runtest(self):
        factory = self.config._tmp_path_factory
        root = factory.mktemp(self.path.stem)
        env = {key: value for key, value in os.environ.items() if not key.startswith("AGENT_COMMS_")}
        # Every script receives private roots, even before it enters its own
        # fixture. Detached children are retired through the existing child owner.
        env.update(
            AGENT_COMMS_ROOT=str(root/'wire'),
            TOAD_TEST_ATTEMPT=str(root),
            XDG_CONFIG_HOME=str(root/'config'),
            XDG_DATA_HOME=str(root/'data'),
            XDG_STATE_HOME=str(root/'state'),
            XDG_CACHE_HOME=str(root/'cache'),
            PI_CODING_AGENT_DIR=str(root/'pi'),
            TMPDIR=str(root),
            TOAD_E2E_ROOT=str(root),
        )
        # No editable package/source overrides: children import the installed
        # wheel. The script directory is Python's normal local fixture boundary.
        env.pop('PYTHONPATH', None)
        env.pop('NO_COLOR', None)
        env.update(TERM="xterm-256color", COLORTERM="truecolor", FORCE_COLOR="1")
        timeout = self.config.getoption('--pilot-timeout')
        stdout, stderr = root/'stdout.log', root/'stderr.log'

        async def run():
            try:
                result = await BoundedRun.run(
                    (sys.executable, str(self.path)), timeout=timeout,
                    cwd=self.config.rootpath, env=env,
                )
                stdout.write_bytes(result.stdout)
                stderr.write_bytes(result.stderr)
                if not result.outcome.successful:
                    pytest.fail(f'Pilot failed: {result.outcome!r}\n{result.stderr.decode(errors="replace")[-12000:]}\nLogs: {root}', pytrace=False)
            finally:
                # UI shutdown deliberately leaves owners alive. Retire only
                # processes whose private fixture root attests this attempt.
                for process in psutil.process_iter():
                    try:
                        identity = ProcessIdentity.capture(process.pid)
                        environment = process.environ()
                        if environment.get("TOAD_TEST_ATTEMPT") == str(root):
                            await DetachedProcess.attach(identity).stop()
                    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
                        continue
        asyncio.run(run())

    def reportinfo(self):
        return self.path, 0, f'pilot: {self.name}'


def pytest_pycollect_makemodule(module_path, parent):
    if not module_path.name.startswith("test_"):
        return PilotFile.from_parent(parent, path=module_path)
