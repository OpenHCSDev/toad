#!/usr/bin/env python3
"""Every `from X import name` under `if TYPE_CHECKING:` names something X binds.

A type-only import never runs, so one that names a moved class or a deleted module stays
wrong unnoticed: eight had (2026-11-20), found when NominalRefactorAdvisor promoted one to a
real import and Toad stopped importing. Run from the checkout; exits 1 and lists each one.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path


def guarded_imports(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and ast.unparse(node.test).endswith("TYPE_CHECKING"):
            yield from (statement for statement in node.body
                        if isinstance(statement, ast.ImportFrom) and statement.module and not statement.level)


def unbound(statement: ast.ImportFrom) -> list[str]:
    """What the import names that its module does not bind, or why the module does not import."""
    try:
        module = importlib.import_module(statement.module)
    except ImportError as error:
        return [f"module does not import ({error})"]
    missing = []
    for alias in statement.names:
        if hasattr(module, alias.name):
            continue
        try:
            importlib.import_module(f"{statement.module}.{alias.name}")
        except ImportError:
            missing.append(alias.name)
    return missing


def main(root: Path) -> int:
    wrong = [(path, statement.lineno, statement.module, name)
             for path in sorted(root.rglob("*.py"))
             for statement in guarded_imports(ast.parse(path.read_text()))
             for name in unbound(statement)]
    for path, line, module, name in wrong:
        print(f"{path}:{line}: `{module}` does not bind {name}")
    print(f"type-only imports naming something their module does not bind: {len(wrong)}")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "src/toad")))
