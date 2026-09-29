"""MCP consumers cannot restore a second decoder, command roster or outcome map."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / 'src/toad'


def test_inventory_uses_the_shared_boundary_decoder():
    tree = ast.parse((ROOT / 'mcp_inventory.py').read_text())
    retired = {'_object', '_boolean', '_rows', '_POLICIES'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in retired
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {'isinstance', 'type'}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != 'get', 'Decoded records replace raw dictionary reads'
    assert any(isinstance(node, ast.Call) and ast.unparse(node.func) == 'FieldCodec.decode'
               for node in ast.walk(tree))


def test_decision_consumers_have_no_parallel_case_rosters():
    for filename in ('mcp_decision.py', 'screens/mcp_inventory.py', 'screens/mcp_decision.py'):
        tree = ast.parse((ROOT / filename).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in {'trust', 'calls', 'approve', 'deny', 'allow', 'ask',
                                          'exited_zero', 'exited_error', 'stale_snapshot',
                                          'controller_lost', 'outcome_unknown'}, (filename, node.lineno)
            if isinstance(node, ast.Name):
                assert node.id not in {'Decision', 'DecisionAction'}


def test_models_do_not_adapt_the_codec():
    # The installed declaration-only new command case exercises actual UI/PTY
    # extension. This guard preserves one boundary form instead of a codec fork.
    for filename in ('mcp_declarations.py', 'mcp_commands.py', 'mcp_outcomes.py'):
        tree = ast.parse((ROOT / filename).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert all(ast.unparse(base) != 'FieldCodec' for base in node.bases)
