#!/usr/bin/env python3
"""PreToolUse hook: while Tristan's testing restriction stands, no test file changes and no test runs.

Exit code 2 blocks the tool call and shows the reason to Claude. Delete this hook to lift the restriction.
"""
from __future__ import annotations

import json
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import ClassVar


@dataclass(frozen=True)
class ToolCall:
    """The tool call, decoded once at the boundary."""

    path: PurePosixPath
    command: str

    @classmethod
    def decode(cls, payload: str) -> ToolCall:
        tool_input = json.loads(payload)["tool_input"]
        return cls(PurePosixPath(tool_input.get("file_path", "")), tool_input.get("command", ""))


class Restriction(ABC):
    reason: ClassVar[str]

    @abstractmethod
    def blocks(self, call: ToolCall) -> bool: ...


class TestFileChange(Restriction):
    reason = "Test files may not change: verify in the real application instead (see CLAUDE.md)."

    def blocks(self, call: ToolCall) -> bool:
        return "tests" in call.path.parts or call.path.name.startswith("test_")


class TestRun(Restriction):
    reason = "Tests may not run: verify in the real application instead (see CLAUDE.md)."
    pattern: ClassVar[re.Pattern[str]] = re.compile(r"\b(pytest|unittest|tox|nox)\b")

    def blocks(self, call: ToolCall) -> bool:
        return bool(self.pattern.search(call.command))


RESTRICTIONS: tuple[Restriction, ...] = (TestFileChange(), TestRun())

call = ToolCall.decode(sys.stdin.read())
reasons = [restriction.reason for restriction in RESTRICTIONS if restriction.blocks(call)]
print("\n".join(reasons), file=sys.stderr)
sys.exit(2 if reasons else 0)
