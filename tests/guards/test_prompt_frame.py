"""Prevent the retired cursor/frame authorities and forwarding callers returning."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src/toad"


def test_retired_prompt_and_frame_callers_are_deleted():
    retired = {
        "CursorMove", "InvokeSlashCompleteMessage", "slash_command_prefixes",
        "_first_frame_presented", "_first_frame_flush_queued", "_presentation_revision",
        "_navigation_frame_pending", "_presented_event", "_initial_frame_callbacks",
        "call_after_first_frame", "_finish_first_frame", "_frame_presented",
    }
    for path in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            match node:
                case ast.Name(id=name) | ast.Attribute(attr=name) | ast.ClassDef(name=name) | ast.FunctionDef(name=name):
                    assert name not in retired, (path, node.lineno, name)


def test_frame_driver_boundary_has_no_capability_probes_or_parallel_roster():
    for relative in ("frame_presentation.py", "prompt_cursor.py"):
        for node in ast.walk(ast.parse((ROOT / relative).read_text())):
            match node:
                case ast.Call(func=ast.Name(id=name)):
                    assert name not in {"getattr", "hasattr", "isinstance"}, (relative, node.lineno)
                case ast.ClassDef(name=name):
                    assert not name.endswith(("Mixin", "Codec")), (relative, node.lineno)
