"""Projection decisions stay with cases; worker cancellation owns scan lifetime."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'src/toad'


def test_deleted_scan_flags_and_external_projection_probes():
    retired = {'ScanState', 'IdleScan', 'ForcedIdleScan', 'RunningScan',
               'ForcedRunningScan', 'force_pending', 'clear_force'}
    for path in (ROOT/'transcript_filter.py', ROOT/'transcript_state.py',
                 ROOT/'widgets/transcript_history.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in retired
            if isinstance(node, ast.Attribute):
                assert node.attr not in retired
                if path.name != 'transcript_filter.py':
                    assert ast.unparse(node) != 'self.filter.overlay'
                    assert ast.unparse(node) != 'owner.filter.overlay'
                elif node.attr in {'_loading', '_advancing'}:
                    raise AssertionError('Filter must ask history admission owner')


def test_filter_workers_receive_callables():
    tree = ast.parse((ROOT/'transcript_filter.py').read_text())
    workers = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == 'run_worker']
    assert workers
    for worker in workers:
        argument = worker.args[0]
        if isinstance(argument, ast.Call):
            assert ast.unparse(argument.func) == 'partial', 'Precreated coroutine can leak on cancellation'


def test_projected_pager_worker_receives_callable():
    tree = ast.parse((ROOT/'widgets/transcript_history.py').read_text())
    request = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                   and n.name == '_request_page')
    workers = [n for n in ast.walk(request) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute) and n.func.attr == 'run_worker']
    assert len(workers) == 1
    assert isinstance(workers[0].args[0], ast.Call)
    assert ast.unparse(workers[0].args[0].func) == 'partial'
