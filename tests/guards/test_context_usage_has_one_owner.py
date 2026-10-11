"""Context usage is read through ContextMeasurement; the old private usage fields and ContextUsage name stay out of Toad."""
import ast
from pathlib import Path


def test_no_source_file_reads_the_old_usage_fields():
    root = Path(__file__).resolve().parents[2] / 'src/toad'
    for path in root.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {'_context_usage', '_context_usage_saved'}, (path, node.lineno)
            if isinstance(node, ast.Name):
                assert node.id != 'ContextUsage', (path, node.lineno)
