"""T4 state/new-case contracts and permanent superseded-authority guards."""

import ast
from pathlib import Path

from textual.app import App

from toad.clipboard import Clipboard
from toad.tab_order import TabOrder


def test_tab_order_branches_closure_and_new_kind():
    app = App()
    focused = []
    order = TabOrder(lambda mode, index: focused.append((mode, index)))
    for mode in ("first", "second", "third"):
        order.open(mode)
        order.record_visit(mode)
    order.navigate(-1)
    mode, index = focused[-1]
    order.record_visit(mode, index)
    order.open("new-kind", after=mode)
    order.record_visit("new-kind")
    assert order.names == ("first", "second", "new-kind", "third")
    assert order.history_target(+1) is None
    assert order.previous("new-kind") == "second"
    order.close({"second", "third"})
    order.navigate(-1)
    assert focused[-1][0] == "first"
    assert order.previous("new-kind") == "first"
    assert order.project({"first": 1, "new-kind": 2, "closed": 3}) == (1, 2)


def test_new_clipboard_case_is_declared_and_uses_common_copy_contract():
    class FutureClipboard(Clipboard):
        def publish(self, app, text):
            app.title = text
            return self

    app = App()
    transport = Clipboard.decode(FutureClipboard.declared_name)()
    assert FutureClipboard in Clipboard.members_with(Clipboard)
    assert transport.copy(app, "one declaration café") is transport
    assert app.title == app.clipboard == "one declaration café"


def test_t4_tab_clipboard_deletion_guards():
    root = Path(__file__).resolve().parents[1] / "src/toad"
    retired = {
        "_open_tab_order",
        "_tab_history",
        "_tab_history_index",
        "_supports_pyperclip",
        "_record_tab_visit",
        "_prune_tab_history",
        "_tab_history_target",
        "navigate_tab_history",
        "can_navigate_tab_history",
        "tab_history_changed",
    }
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                assert node.attr not in retired, (path, node.lineno, node.attr)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in retired, (path, node.lineno, node.name)
            if isinstance(node, ast.Import) and path.name != "clipboard.py":
                assert all(alias.name != "pyperclip" for alias in node.names), path
            if isinstance(node, ast.ImportFrom) and path.name != "clipboard.py":
                assert node.module != "pyperclip", path
    assert not (root.parents[1] / "tests/clipboard_selection_pilot.py").exists()
