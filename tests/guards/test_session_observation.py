"""Retired root readers cannot return."""
import ast
from pathlib import Path


def test_retired_root_readers_deleted():
    source = Path(__file__).parents[2] / 'src/toad/widgets/conversation.py'
    retired = {'_goal_refresh_task', '_goal_refresh_revision', '_delivery_refresh_task',
               '_delivery_refresh_revision', '_read_goal_snapshot', '_read_input_dispositions',
               '_load_delivery_history', '_dismiss_delivery_history', 'refresh_goal',
               'refresh_input_dispositions', '_invalidate_goal_snapshot', '_invalidate_input_dispositions'}
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Attribute):
            assert node.attr not in retired
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in retired
