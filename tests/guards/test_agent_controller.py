"""Operational custody cannot return to optional rich presentation."""
import ast
from pathlib import Path


def test_operational_owner_deletions():
    source = Path(__file__).parents[2] / "src/toad"
    agent = ast.parse((source / "acp/agent.py").read_text())
    for node in ast.walk(agent):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"_message_target", "_pending_permission_answers", "coordination_facts"}
    messages = ast.parse((source / "acp/messages.py").read_text())
    request = next(node for node in messages.body if isinstance(node, ast.ClassDef) and node.name == "RequestPermission")
    assert [node.target.id for node in request.body if isinstance(node, ast.AnnAssign)] == ["request"]
    conversation = ast.parse((source / "widgets/conversation.py").read_text())
    unmount = next(node for node in ast.walk(conversation) if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_unmount")
    assert not any(isinstance(node, ast.Attribute) and node.attr == "stop" for node in ast.walk(unmount)
                   if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and node.value.attr == "agent")
