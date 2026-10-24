"""Deleted action string routing must not return outside its declaration owner."""

import ast
from pathlib import Path

from agent_comms.cli_commands import (
    ChannelsCliCommand,
    TargetBatchResult,
    TargetCompleted,
    TargetFailed,
)
from agent_comms.cli_result import ResultShower, ToolCatalogResult

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
        TargetCompleted("started", ChannelsCliCommand(), ToolCatalogResult(())),
        TargetFailed("failed", "RuntimeError", "No provider configured"),
    ))

    result.show(shower, "Start", "Threads")

    assert shower.done == [("Start: started", "Threads")]
    assert shower.failures == [("failed: RuntimeError: No provider configured", "Threads")]
