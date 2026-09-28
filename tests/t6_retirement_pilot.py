"""Permanent guards for mechanisms removed by the T6 owner."""

import ast
from pathlib import Path
import unittest


class RenderingRetirementTests(unittest.TestCase):
    def test_retired_owners_and_category_groupings_are_absent(self):
        import toad

        root = Path(toad.__file__).parent
        retired = {
            "RenderCommandKind",
            "RenderStatus",
            "RendererBackend",
            "HistoryKind",
            "RENDER_TASK_TYPES",
            "RendererTask",
            "RendererResult",
            "MESSAGE_LABELS",
            "MESSAGE_CATEGORIES",
            "ALL_CATEGORIES",
            "IN_OUT_CATEGORIES",
            "create_renderer",
            "reusable_result",
        }
        violations = []
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Name) and node.id in retired:
                    violations.append((str(path), node.lineno, node.id))
                if isinstance(node, ast.Attribute) and node.attr in retired:
                    violations.append((str(path), node.lineno, node.attr))
                if (
                    isinstance(
                        node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                    )
                    and node.name in retired
                ):
                    violations.append((str(path), node.lineno, node.name))
                if isinstance(node, ast.ImportFrom):
                    violations.extend(
                        (str(path), node.lineno, name.name)
                        for name in node.names
                        if name.name in retired
                    )
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "AgentResponse"
                    and any(keyword.arg == "route" for keyword in node.keywords)
                ):
                    violations.append((str(path), node.lineno, "untyped response route"))
                if isinstance(node, ast.Set) and any(
                    isinstance(item, ast.Attribute)
                    and isinstance(item.value, ast.Name)
                    and item.value.id == "MessageCategory"
                    for item in node.elts
                ):
                    violations.append(
                        (str(path), node.lineno, "manual category grouping")
                    )
                if (
                    path.name == "render_zmq.py"
                    and isinstance(node, ast.Attribute)
                    and node.attr in {"status", "admitted"}
                ):
                    violations.append((str(path), node.lineno, node.attr))
                if path.name == "comms_chat.py" and isinstance(node, ast.Compare):
                    if any(
                        isinstance(part, ast.Constant)
                        and part.value in {"dm", "channel", "irc"}
                        for part in node.comparators
                    ):
                        violations.append(
                            (
                                str(path),
                                node.lineno,
                                "conversation kind string dispatch",
                            )
                        )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
