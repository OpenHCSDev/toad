"""Real native acceptance must exercise the production bootstrap."""
import ast
from pathlib import Path


def test_native_pilot_does_not_install_runtime_schemas():
    pilot = Path(__file__).parents[1] / "l0a_native_installed_pilot.py"
    tree = ast.parse(pilot.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not any(alias.name.startswith("install_") for alias in node.names)
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            assert not name.startswith("install_")
