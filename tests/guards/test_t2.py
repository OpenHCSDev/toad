"""T2 has one shared wire family and no local copy of its messages or flags."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "toad"


def test_retired_protocol_surface_is_deleted():
    retired = (
        "ownerEpoch",
        "owner_epoch",
        "admission_epoch",
        "QueueReducer",
        "parse_cursor",
        "CoordinationUpdate",
        "CompactionUpdate",
        "PrivateNativeCursorUpdate",
        "QueueViewUpdate",
        "supports_prompt_queue",
        "supports_prompt_images",
        "uses_turn_events",
        "server_titles",
    )
    for path in ROOT.rglob("*.py"):
        source = path.read_text()
        for name in retired:
            assert name not in source, (path, name)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and node.value == "agentComms":
                raise AssertionError(
                    f"Local extension schema access: {path}:{node.lineno}"
                )
    assert not (ROOT / "acp" / "queue_view.py").exists()
