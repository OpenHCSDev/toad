"""Collect script pilots once, using the installed pinned stack and bounded children."""

import asyncio
import os
from pathlib import Path
import sys
import time

import pytest
from agent_comms.child_process import NamespacedChild


def pytest_addoption(parser):
    parser.addoption('--pilot-timeout', type=float, default=90,
                     help='One attempt per pilot, bounded wall seconds (no retries)')


class PilotFile(pytest.File):
    def collect(self):
        yield Pilot.from_parent(self, name=self.path.stem)


class Pilot(pytest.Item):
    def runtest(self):
        factory = self.config._tmp_path_factory
        root = factory.mktemp(self.path.stem)
        env = {key: value for key, value in os.environ.items() if not key.startswith("AGENT_COMMS_")}
        # Every script receives private roots, even before it enters its own
        # fixture. Detached children are contained by the existing kernel owner.
        env.update(
            AGENT_COMMS_ROOT=str(root/'wire'),
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
        timeout = self.config.getoption('--pilot-timeout')
        stdout, stderr = root/'stdout.log', root/'stderr.log'

        async def run():
            child = await NamespacedChild.start(
                ("unshare", "--net", sys.executable, str(Path(__file__).with_name("pilot_entrypoint.py")), str(self.path)), deadline=time.monotonic()+timeout,
                cwd=self.config.rootpath, env=env,
            )
            async def capture(stream, path):
                with path.open('wb') as output:
                    while chunk := await stream.read(65536):
                        output.write(chunk)
            try:
                async with asyncio.timeout(timeout):
                    async with asyncio.TaskGroup() as readers:
                        readers.create_task(capture(child.stdout, stdout))
                        readers.create_task(capture(child.stderr, stderr))
                        result = await child.wait()
                if not result.successful:
                    pytest.fail(f'Pilot failed: {result!r}\n{stderr.read_text(errors="replace")[-12000:]}\nLogs: {root}', pytrace=False)
            finally:
                await child.stop()
        asyncio.run(run())

    def reportinfo(self):
        return self.path, 0, f'pilot: {self.name}'


def pytest_collect_file(file_path, parent):
    if file_path.name.endswith('_pilot.py'):
        return PilotFile.from_parent(parent, path=file_path)
