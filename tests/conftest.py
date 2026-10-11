"""How Toad's tests run: app tests get a process and private roots each; coroutine tests just run."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from support.requirements import Requirement
from support.roots import ATTEMPT, Roots
from support.workspace import Workspace

RESULT = "TOAD_TEST_RESULT"
pytest_plugins = ["legacy_pilots"]


def pytest_addoption(parser):
    parser.addoption("--test-timeout", type=float, default=165,
                     help="Wall seconds one app test may take, once (no retries)")


@pytest.fixture
def workspace() -> Workspace:
    """A private project and wire; asking for it gives the test its own process."""
    return Workspace(Roots.of_this_process())


for _requirement in Requirement.__subclasses__():
    globals()[_requirement.fixture] = pytest.fixture(name=_requirement.fixture)(_requirement.require)


class OwnProcessTest(pytest.Item):
    """Runs one collected test in a fresh interpreter that owns disposable roots.

    The app keeps process-wide state (render workers, the comms route, settings
    paths, frozen heap), so two app tests never share an interpreter.
    """

    def runtest(self):
        from agent_comms.child_process import BoundedRun
        from support.processes import stop_test_children

        roots = Roots.create()
        result = roots.attempt / "result.jsonl"
        env = roots.environment(dict(os.environ)) | {RESULT: str(result)}
        command = (sys.executable, "-m", "pytest", self.nodeid, "-p", "no:cacheprovider",
                   "-q", "--no-header", "--tb=short", "--color=no")

        async def run():
            try:
                return await BoundedRun.run(command, timeout=self.config.getoption("--test-timeout"),
                                            cwd=self.config.rootpath, env=env)
            finally:
                # Closing the app leaves owners and helpers running; stop the ones this test started.
                await stop_test_children(str(roots.attempt))

        child = asyncio.run(run())
        reports = [json.loads(line) for line in result.read_text().splitlines()] if result.exists() else []
        output = child.stdout.decode(errors="replace")[-12000:] + child.stderr.decode(errors="replace")[-4000:]
        if not child.outcome.successful or not reports:
            pytest.fail(f"{child.outcome!r}\n{output}\nRoots kept: {roots.attempt}", pytrace=False)
        shutil.rmtree(roots.attempt)
        for report in reports:
            if report["outcome"] == "skipped":
                pytest.skip(report["reason"])

    def reportinfo(self):
        return self.path, None, self.name


def pytest_collection_modifyitems(config, items):
    if ATTEMPT in os.environ:
        return  # This is the process a test was given.
    items[:] = [OwnProcessTest.from_parent(item.parent, name=item.name)
                if "workspace" in getattr(item, "fixturenames", ()) else item for item in items]


def pytest_runtest_logreport(report):
    if (path := os.environ.get(RESULT)) is None:
        return
    reason = report.longrepr[2].removeprefix("Skipped: ") if report.skipped else ""
    with Path(path).open("a") as stream:
        stream.write(json.dumps({"when": report.when, "outcome": report.outcome, "reason": reason}) + "\n")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Coroutine tests run on their own event loop."""
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    arguments = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
    asyncio.run(pyfuncitem.obj(**arguments))
    return True
