"""Operational ownership cannot return to optional rich presentation."""
import ast
from pathlib import Path


def test_operational_owner_deletions():
    source = Path(__file__).parents[2] / "src/toad"
    agent = ast.parse((source / "acp/agent.py").read_text())
    for node in ast.walk(agent):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"_message_target", "_pending_permission_answers", "coordination_facts"}
    conversation = ast.parse((source / "widgets/conversation.py").read_text())
    unmount = next(node for node in ast.walk(conversation) if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_unmount")
    assert not any(isinstance(node, ast.Attribute) and node.attr == "stop" for node in ast.walk(unmount)
                   if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and node.value.attr == "agent")


def test_human_capture_uses_the_queue_owner():
    source = Path(__file__).parents[2] / 'src/toad/acp/agent_controller.py'
    module = ast.parse(source.read_text())
    submit = next(node for node in ast.walk(module)
                  if isinstance(node, ast.AsyncFunctionDef) and node.name == '_submit')
    assert not any(isinstance(node, ast.Name) and node.id == 'HumanInputOrigin'
                   for node in ast.walk(submit))
    assert not any(isinstance(node, ast.Compare)
                   and isinstance(node.left, ast.Name) and node.left.id == 'queue_scope'
                   for node in ast.walk(submit))
    assert any(isinstance(node, ast.Attribute) and node.attr == 'capture_human_input'
               for node in ast.walk(submit))
