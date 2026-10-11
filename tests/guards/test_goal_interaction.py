"""Declaration-only control discovery and deleted root goal dispatch."""
import ast
from pathlib import Path


def test_deleted_root():
    tree=ast.parse((Path(__file__).parents[2]/'src/toad/widgets/conversation.py').read_text())
    retired={'_goal_modal','_poll_goal','change_goal'}
    assert not [n for n in ast.walk(tree)
                if isinstance(n,ast.Attribute) and n.attr in retired
                or isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in retired]
    handler=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='on_goal_control')
    assert not any(isinstance(n,ast.Compare) for n in ast.walk(handler))
