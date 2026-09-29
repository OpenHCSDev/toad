"""Availability and provenance stay owned by one context measurement."""
import ast
from pathlib import Path
from toad.acp.context_measurement import ContextMeasurement, ContextUnavailable


def test_context_measurement_family():
    unknown = ContextMeasurement.saved(None)
    assert not unknown.available and 'Native owner has not reported' in unknown.status().plain
    for used, size in ((0, 272000), (120, 0), (-1, 120)):
        unknown = ContextMeasurement.live(used, size, None)
        assert not unknown.available
        assert '%' not in unknown.status().plain
    live = ContextMeasurement.live(38723, 272000, {'amount': .5, 'currency': 'USD'})
    assert live.percentage_display == '14.2%'
    assert 'last response' not in live.status().plain
    from agent_comms.acp_extension import ContextUsage
    saved = ContextMeasurement.saved(ContextUsage(38723, 272000))
    assert saved.used == live.used and saved.size == live.size
    assert 'last response' in saved.status().plain
    assert 'invalidated by compaction' in ContextUnavailable('Context measurement invalidated by compaction').status().plain


def test_context_projection_deleted_callers():
    root = Path(__file__).resolve().parents[1] / 'src/toad'
    for path in root.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {'_context_usage', '_context_usage_saved'}, (path, node.lineno)
            if isinstance(node, ast.Name):
                assert node.id != 'ContextUsage', (path, node.lineno)
