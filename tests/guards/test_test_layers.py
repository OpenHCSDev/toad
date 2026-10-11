"""Each test directory keeps to what its layer may depend on (docs/agents/TESTS.md)."""

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
FRONTEND = ("textual", "toad.widgets", "toad.screens", "toad.app", "toad.textual_colours")
TEXTUAL_ONLY_ATTRIBUTES = {"textual", "pilot", "conversation", "painted", "_compositor"}


def modules(directory: str) -> list[Path]:
    return sorted((TESTS / directory).glob("test_*.py"))


def imported(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def frontend_imports(path: Path) -> list[str]:
    return sorted(name for name in imported(ast.parse(path.read_text()))
                  if any(name == module or name.startswith(module + ".") for module in FRONTEND))


@pytest.mark.parametrize("directory", ["model", "app"])
def test_neutral_layers_import_no_frontend(directory):
    found = {path.name: names for path in modules(directory) if (names := frontend_imports(path))}
    assert not found, f"tests/{directory} must not import the Textual frontend: {found}"


def test_model_tests_do_not_start_the_app():
    for path in modules("model"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert "workspace" not in {argument.arg for argument in node.args.args}, (
                    f"{path.name}:{node.name} starts the app; it belongs in tests/app or tests/textual")


def test_app_tests_ask_only_neutral_questions():
    for path in modules("app"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "ui":
                assert node.attr not in TEXTUAL_ONLY_ATTRIBUTES, (
                    f"{path.name} reaches Textual through ui.{node.attr}; it belongs in tests/textual")


def test_textual_tests_say_what_textual_owns():
    for path in modules("textual"):
        docstring = ast.get_docstring(ast.parse(path.read_text())) or ""
        assert docstring.startswith("Textual-facing:"), f"{path.name} must open with 'Textual-facing: <what Textual owns here>'"


def test_source_names_no_machine_path():
    for path in sorted((TESTS.parent / "src").rglob("*.py")):
        assert "/" + "home/" not in path.read_text(), f"{path} names a machine path"


def test_tests_take_outside_requirements_from_fixtures():
    """No test reads a required environment variable or hard-codes a home directory."""
    for path in sorted(TESTS.rglob("test_*.py")):
        source = path.read_text()
        assert "/" + "home/" not in source, f"{path.name} names a machine path"
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                raise AssertionError(f"{path.name}:{node.lineno} reads os.environ[...]; use a fixture from support.requirements")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorator in node.decorator_list:
                    assert "mark.skip" not in ast.unparse(decorator) and "mark.xfail" not in ast.unparse(decorator), (
                        f"{path.name}:{node.name} is skipped by decoration; a skip must name a requirement")
