"""What the scripted completion agent (``peer("completion")``) recorded in the project."""

from __future__ import annotations

import json


def completion_prompts(workspace) -> list[str]:
    """The prompts the completion peer received, oldest first."""
    record = workspace.project / "completion-wire.jsonl"
    rows = [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
    return [row["prompt"] for row in rows if "prompt" in row]
