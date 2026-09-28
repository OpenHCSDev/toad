"""No production caller can restore retired Goal readers or thread purging."""

import ast
from pathlib import Path


def main():
    findings = []
    for path in (Path(__file__).resolve().parents[1] / "src/toad").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            retired = (
                isinstance(node, ast.Constant)
                and node.value == "comms_delete"
                or isinstance(node, (ast.Name, ast.ClassDef))
                and (node.id if isinstance(node, ast.Name) else node.name)
                in {"SessionDelete", "PromptQueueUpdate"}
                or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "session_delete"
                or isinstance(node, ast.Attribute)
                and (
                    node.attr
                    in {"SessionDelete", "session_delete", "PromptQueueUpdate"}
                    or isinstance(node.value, ast.Name)
                    and node.value.id == "Goal"
                    and node.attr in {"from_wire", "from_registry"}
                    or node.attr == "delete"
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "threads"
                )
            )
            if path.name == "agent.py" and isinstance(node, ast.Compare):
                retired |= (
                    isinstance(node.left, ast.Constant)
                    and node.left.value in {"queue", "restored"}
                    and any(isinstance(op, ast.In) for op in node.ops)
                    and any(
                        isinstance(value, ast.Name) and value.id == "state"
                        for value in node.comparators
                    )
                )
            if retired:
                findings.append(f"{path.name}:{node.lineno}")
    assert not findings, "\n".join(findings)
    print("L0A guard: no retired Goal decoder, purge caller or text-only queue reader")


if __name__ == "__main__":
    main()
