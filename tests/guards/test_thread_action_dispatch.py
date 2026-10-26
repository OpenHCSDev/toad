"""Deleted action string routing must not return outside its declaration owner."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

from agent_comms.channel_targets import ThreadTarget
from agent_comms.cli_verbs.channels import ChannelsCliCommand
from agent_comms.cli_command import (
    TargetBatchResult,
    TargetCompleted,
    TargetFailed,
)
from agent_comms.cli_result import ResultShower, ToolCatalogResult
from agent_comms.restart_refusals import OwnerBusyRefusal

from toad.thread_actions import ThreadActionExecution

SOURCE = Path(__file__).resolve().parents[2] / "src/toad"
ACTION_NAMES = {"comms_start", "comms_stop", "comms_archive", "comms_ack", "comms_fork"}


def test_no_string_control_eligibility_or_tool_catalog_consumers_remain():
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "allows_control":
                raise AssertionError((path, node.lineno, "retired string control eligibility"))
            if isinstance(node, ast.ImportFrom) and node.module == "agent_comms.tools":
                assert not {entry.name for entry in node.names} & {"TOOLS", "ToolDeclaration", "ToolParameter"}, (
                    path, node.lineno)


def test_action_names_are_not_strings_outside_their_declaration_owner():
    for path in SOURCE.rglob("*.py"):
        if path.name == "thread_actions.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in ACTION_NAMES, (path, node.lineno, node.value)


class RecordingResultShower(ResultShower):
    def __init__(self) -> None:
        self.done: list[tuple[str, str]] = []
        self.failures: list[tuple[Exception | str, str]] = []

    def show_done(self, text: str, title: str) -> None:
        self.done.append((text, title))

    def show_error(self, error: Exception | str, title: str) -> None:
        self.failures.append((error, title))


def test_mixed_target_batch_shows_each_outcome_once() -> None:
    shower = RecordingResultShower()
    result = TargetBatchResult((
        TargetCompleted(ThreadTarget("started"), ChannelsCliCommand(), ToolCatalogResult(())),
        TargetFailed(ThreadTarget("failed"), "RuntimeError", "No provider configured"),
    ))

    result.show(shower, "Start", "Threads")

    assert shower.done == [("Start: started", "Threads")]
    assert shower.failures == [("failed: RuntimeError: No provider configured", "Threads")]


class RefusingApp(RecordingResultShower):
    """Runs the action's worker inline, as Toad's preparation thread would."""

    def __init__(self) -> None:
        super().__init__()
        self.preparation = self
        self.tasks: list[asyncio.Task] = []

    async def run_thread(self, apply):
        return apply()

    def run_worker(self, work, name: str) -> asyncio.Task:
        self.tasks.append(asyncio.ensure_future(work))
        return self.tasks[-1]


class RefusedExecution(ThreadActionExecution):
    def apply(self):
        raise OwnerBusyRefusal()


def test_core_refusal_is_shown_and_releases_the_action() -> None:
    app = RefusingApp()
    finished: list[ThreadActionExecution] = []
    owner = SimpleNamespace(app=app, finished=finished.append)
    action = SimpleNamespace(definition=SimpleNamespace(label="Restart"))

    async def run() -> RefusedExecution:
        execution = RefusedExecution(owner, action, None, "unit-backend")
        await asyncio.gather(*app.tasks)
        return execution

    execution = asyncio.run(run())

    assert [(str(error), title) for error, title in app.failures] == [
        ("Wait until the owner is idle before restart.", "Restart")]
    assert finished == [execution]
