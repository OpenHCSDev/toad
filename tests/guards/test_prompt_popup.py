"""Retired root mechanisms and duplicate scorers cannot return."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src/toad"


def test_popup_owner_and_caller_deletion():
    retired = {"PromptCompletion", "show_path_search", "show_slash_complete", "InvokeFileSearch",
               "open_path_search", "watch_show_path_search", "watch_show_slash_complete"}
    for path in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            match node:
                case ast.Name(id=name) | ast.Attribute(attr=name) | ast.ClassDef(name=name) | ast.FunctionDef(name=name):
                    assert name not in retired, (path, node.lineno, name)
    assert not (ROOT / "_path_match.py").exists()
    assert "-show-path-search" not in (ROOT / "screens/main.tcss").read_text()
    assert "-show-slash-complete" not in (ROOT / "screens/main.tcss").read_text()
    path_search = (ROOT / "widgets/path_search.py").read_text()
    assert "InterpreterPoolExecutor" not in path_search and "match_path" not in path_search


def test_completion_members_trust_composer_admission():
    # These two consumers used to repeat the other object's input-state probes.
    # The actual installed family pilot protects eligibility and focus behavior.
    for filename in ("path_search.py", "slash_complete.py"):
        tree = ast.parse((ROOT / "widgets" / filename).read_text())
        for node in ast.walk(tree):
            match node:
                case ast.UnaryOp(op=ast.Not(), operand=ast.Attribute(value=ast.Attribute(value=ast.Name(id="self"), attr="prompt"))):
                    raise AssertionError((filename, node.lineno, "Composer state belongs to Prompt"))
