"""The transcript history keeps its lifecycle in its state objects, not in flags on the widget."""

import ast
from importlib.util import find_spec
from pathlib import Path


def test_transcript_history_reads_and_writes_no_lifecycle_flag():
    path = Path(find_spec("toad.widgets.transcript_history").origin)
    attributes = {node.attr for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Attribute)}
    assert not attributes & {"_committed", "_closing", "_pruning"}
