"""T1's deleted dispatch and string-read mechanisms cannot return."""

import ast
from pathlib import Path


def test_settings_ownership_guards():
    root = Path(__file__).resolve().parents[1] / "src" / "toad"
    assert not (root / "settings_schema.py").exists()
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and node.name in {"setting_updated", "schema_to_widget", "get_setting"}:
                violations.append((str(path.relative_to(root)), node.lineno, node.name))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"get", "set"}
            ):
                owner = node.func.value
                if (isinstance(owner, ast.Name) and owner.id == "settings") or (
                    isinstance(owner, ast.Attribute) and owner.attr == "settings"
                ):
                    violations.append(
                        (
                            str(path.relative_to(root)),
                            node.lineno,
                            "untyped settings access",
                        )
                    )
        if path.name == "settings.py":
            assert not any(
                isinstance(node, ast.ClassDef)
                and node.name in {"Schema", "SchemaDict", "Setting", "Settings"}
                for node in ast.walk(tree)
            )
            assert not any(
                isinstance(node, ast.Name) and node.id == "INPUT_TYPES"
                for node in ast.walk(tree)
            )
    for path in (root / "widgets").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_settings_changed"
            ):
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and child.value in {
                        "sidebar.hide",
                        "sidebar.show_stopped",
                        "sidebar.show_archived",
                        "ui.recovery-view",
                        "shell.allow_commands",
                    }:
                        violations.append(
                            (
                                str(path.relative_to(root)),
                                child.lineno,
                                "string change routing",
                            )
                        )
    assert not violations, violations


if __name__ == "__main__":
    test_settings_ownership_guards()
    print("PASS settings deletion guards")
