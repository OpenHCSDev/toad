"""Projection decisions stay with cases; worker cancellation owns scan lifetime."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'src/toad'


def test_deleted_scan_flags_and_external_projection_probes():
    retired = {'ScanState', 'IdleScan', 'ForcedIdleScan', 'RunningScan',
               'ForcedRunningScan', 'force_pending', 'clear_force',
               'FilterSnapshot', 'filter_snapshot', 'filter_publication_available'}
    overlays = ast.parse((ROOT/'transcript_filter.py').read_text())
    overlay = next(node for node in ast.walk(overlays)
                   if isinstance(node, ast.ClassDef) and node.name == 'NoProjectionOverlay')
    operations = {node.name for node in overlay.body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for path in (ROOT/'transcript_filter.py', ROOT/'transcript_state.py',
                 ROOT/'widgets/transcript_history.py'):
        tree = ast.parse(path.read_text())
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in retired
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in retired
            if isinstance(node, ast.Attribute):
                assert node.attr not in retired
                if path.name != 'transcript_filter.py' and ast.unparse(node) in {'self.filter.overlay', 'owner.filter.overlay'}:
                    parent = parents[node]
                    # Calling the shared overlay protocol delegates behavior;
                    # comparing identities fences a replaced projection. Neither
                    # inspects which projection case is active.
                    delegated = (isinstance(parent, ast.Attribute) and parent.attr in operations
                                 and isinstance(parents.get(parent), ast.Call)
                                 and parents[parent].func is parent)
                    identity = (isinstance(parent, ast.Compare)
                                and all(isinstance(op, (ast.Is, ast.IsNot)) for op in parent.ops)
                                and not any(isinstance(value, ast.Constant)
                                            for value in (parent.left, *parent.comparators)))
                    assert delegated or identity, (path, node.lineno, ast.unparse(parent))
                elif path.name == 'transcript_filter.py' and node.attr in {'_loading', '_advancing', '_generation', '_selected_categories', '_prefetch_distance'}:
                    raise AssertionError('Filter must ask history admission owner')


def test_source_and_body_owners_do_not_reacquire_six_term_gates():
    """Seal the final two sites and their shared declaration owners."""
    for relative in ('transcript_filter.py', 'transcript_source_preparation.py',
                     'widgets/transcript_history.py'):
        for node in ast.walk(ast.parse((ROOT / relative).read_text())):
            if isinstance(node, ast.BoolOp):
                assert len(node.values) < 6, (relative, node.lineno, ast.unparse(node))


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
    projection = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == 'ProjectedTranscriptHistory')
    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name == '_request_page' for node in projection.body)
    # The projection inherits the pager's operation. Its
    # WorkingTranscript, not an override in a widget, owns worker scheduling.
    states = ast.parse((ROOT/'transcript_state.py').read_text())
    working = next(node for node in states.body if isinstance(node, ast.ClassDef)
                   and node.name == 'WorkingTranscript')
    schedule = next(node for node in working.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'schedule')
    workers = [node for node in ast.walk(schedule) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == 'run_worker']
    assert len(workers) == 1
    assert isinstance(workers[0].args[0], ast.Call)
    assert ast.unparse(workers[0].args[0].func) == 'partial'
