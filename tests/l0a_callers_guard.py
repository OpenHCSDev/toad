"""No production caller can restore retired Goal readers or thread purging."""

import ast
from pathlib import Path


def main():
    findings = []
    for path in (Path(__file__).resolve().parents[1] / "src/toad").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            retired = (
                isinstance(node, ast.Constant) and node.value == "comms_delete"
                or isinstance(node, ast.Name) and node.id == "SessionDelete"
                or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "session_delete"
                or isinstance(node, ast.Attribute) and (
                    node.attr in {"SessionDelete", "session_delete"}
                    or isinstance(node.value, ast.Name) and node.value.id == "Goal"
                    and node.attr in {"from_wire", "from_registry"}
                    or node.attr == "delete" and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "threads"
                )
            )
            if retired:
                findings.append(f"{path.name}:{node.lineno}")
    assert not findings, "\n".join(findings)
    print("L0A guard: no retired Goal decoder or thread-purge production callers")


if __name__ == "__main__":
    main()
