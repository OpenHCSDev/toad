"""Prevent the deleted App counter/timer/dispatch API from returning."""
import ast
from pathlib import Path


def test_attention_caller_closure():
    root = Path(__file__).parents[2] / "src/toad"
    retired = {"terminal_title_flash", "terminal_title_blink", "_terminal_title_flash_timer",
               "terminal_alert", "system_notify", "update_terminal_title", "term_program"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        assert not any(node.attr in retired for node in ast.walk(tree)
                       if isinstance(node, ast.Attribute)), path
        assert not any(node.name in retired for node in ast.walk(tree)
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))), path
    assert not any(isinstance(node, ast.ClassDef) and node.name.endswith("FieldCodec")
                   for node in ast.walk(ast.parse((root / "terminal_attention.py").read_text())))


if __name__ == "__main__":
    test_attention_caller_closure()
    print("PASS retired counter/timer/notification caller API absent; no FieldCodec")
