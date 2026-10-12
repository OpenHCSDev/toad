"""The native test fixture starts Core the way production does: it installs no runtime schema itself."""
import ast
from pathlib import Path


def test_native_fixture_does_not_install_runtime_schemas():
    owner = Path(__file__).parents[1] / "support" / "native.py"
    tree = ast.parse(owner.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not any(alias.name.startswith("install_") for alias in node.names)
        if isinstance(node, ast.Call):
            name = (node.func.id if isinstance(node.func, ast.Name)
                    else node.func.attr if isinstance(node.func, ast.Attribute) else "")
            assert not name.startswith("install_")
