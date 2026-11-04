"""Production configuration never selects behavior through test-only switches."""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src/toad"


def test_no_product_test_environment_switch():
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                environment = ast.unparse(node.func.value)
                if environment == "os.environ" or (environment == "os" and node.func.attr == "getenv"):
                    if node.args and isinstance(node.args[0], ast.Constant):
                        assert "TEST" not in str(node.args[0].value), (path, node.lineno)
            if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                if isinstance(node.slice, ast.Constant):
                    assert "TEST" not in str(node.slice.value), (path, node.lineno)
