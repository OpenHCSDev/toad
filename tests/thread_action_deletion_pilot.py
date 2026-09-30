"""Deleted action string routing must not return outside its declaration owner."""
import ast
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[1] / 'src/toad'
    names = {'comms_start', 'comms_stop', 'comms_archive', 'comms_ack', 'comms_fork'}
    for path in source.rglob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == 'allows_control':
                raise AssertionError((path, node.lineno, 'retired string control eligibility'))
            if isinstance(node, ast.ImportFrom) and node.module == 'agent_comms.tools':
                assert not {entry.name for entry in node.names} & {
                    'TOOLS', 'ToolDeclaration', 'ToolParameter'
                }, (path, node.lineno)
        if path.name == 'thread_actions.py':
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in names, (path, node.lineno, node.value)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {'invoke_context_tool', 'context_tool_catalog'}, (path, node.lineno)
    print('thread actions: zero retired string dispatch/catalog consumers')


if __name__ == '__main__':
    main()
