"""The scripted completion agent (tests/acp_completion_server.py) as an agent definition, and what it recorded.

The completion peer is being moved to ``support/peers/completion.py`` by another
change; once it is there, use ``peer("completion")`` instead of ``completion_agent()``
and delete this module.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from support.agents import command

SERVER = Path(__file__).resolve().parents[1] / "acp_completion_server.py"


def completion_agent(name: str = "Completion peer", identity: str = "completion-peer"):
    return command(sys.executable, str(SERVER), name=name, identity=identity)


def completion_prompts(workspace) -> list[str]:
    """The prompts the completion peer received, oldest first."""
    record = workspace.project / "completion-wire.jsonl"
    rows = [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
    return [row["prompt"] for row in rows if "prompt" in row]
