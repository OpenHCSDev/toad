"""Root deletion and one declaration-only new live stream case."""
import ast
from pathlib import Path


def test_root_has_no_stream_store():
    path = Path(__file__).parents[2] / 'src/toad/widgets/conversation.py'
    tree = ast.parse(path.read_text())
    removed = {'_agent_response', '_agent_thought', '_post_lock', 'post_agent_response', 'post_agent_thought', 'new_block'}
    assert not [node for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr in removed
                or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in removed]
