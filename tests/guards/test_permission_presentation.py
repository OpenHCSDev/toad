"""External decode is confined to the request; root never selects a presentation."""
import ast
from pathlib import Path


def test_deleted_dispatch():
    root=Path(__file__).parents[2]
    tree=ast.parse((root/'src/toad/widgets/conversation.py').read_text())
    body=next(node for node in ast.walk(tree) if isinstance(node,ast.AsyncFunctionDef)
              and node.name=='request_permissions')
    assert not any(isinstance(node,(ast.If,ast.For,ast.Match)) for node in ast.walk(body))
    assert not any(isinstance(node,ast.Attribute) and node.attr=='tool_call' for node in ast.walk(body))
    controller=ast.parse((root/'src/toad/acp/permission_controller.py').read_text())
    assert not any(isinstance(node,ast.Attribute) and node.attr=='_tool_call' for node in ast.walk(controller))
