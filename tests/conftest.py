"""How Toad's tests run: app tests get a process and private roots each; coroutine tests just run."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
import warnings

import pytest

from support.agents import AppAgents
from support.requirements import Requirement
from support.roots import ATTEMPT, Roots
from support.workspace import Workspace

RESULT = "TOAD_TEST_RESULT"
OPEN_DEFECTS = Path(__file__).with_name("open_defects.toml")


class OrphanDefect(pytest.PytestWarning):
    """An open defect stays recorded after its test is deleted; it needs a new reproducer."""


def open_defects() -> dict[str, str]:
    """Recorded investigations annotate results; each run owns its actual outcome."""
    import tomllib

    return {test: f"Recorded defect {name} ({entry['owner']}): {entry['defect']}"
            for name, entry in tomllib.loads(OPEN_DEFECTS.read_text()).items() for test in entry["tests"]}


def pytest_addoption(parser):
    parser.addoption("--test-timeout", type=float, default=165,
                     help="Wall seconds one app test may take, once (no retries)")


@pytest.fixture
def launch_root(tmp_path):
    """The comms root the test's app selects: a private one; a module overrides it to need another."""
    from agent_comms.launch_root import LaunchRoot

    return LaunchRoot.from_path(tmp_path / "wire")


@pytest.fixture
def app_agents(tmp_path, launch_root) -> Iterator[AppAgents]:
    """Agents of an app built on the test's own directory and never run."""
    with launch_root.selected():
        yield AppAgents.unrun(tmp_path)


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
        failed = not child.outcome.successful or not reports
        if failed:
            (roots.attempt / "stdout.log").write_bytes(child.stdout)
            (roots.attempt / "stderr.log").write_bytes(child.stderr)
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
    defects = open_defects()
    if not config.args_source == config.ArgsSource.ARGS:
        for test in sorted(set(defects) - {item.nodeid for item in items}):
            warnings.warn(OrphanDefect(f"{defects[test]} Its test {test} no longer exists: the defect needs a new test."))
    items[:] = [OwnProcessTest.from_parent(item.parent, name=item.name)
                if "workspace" in getattr(item, "fixturenames", ()) else item for item in items]
    for item in items:
        if note := defects.get(item.nodeid):
            item.add_report_section("call", "Recorded defect", note)


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
