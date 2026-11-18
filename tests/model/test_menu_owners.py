"""Each element's context menu is declared once, on the shared parent both frontends'
elements inherit, and a toolkit only draws it (Tristan, 2026-11-18: "they shouldn't EVEN
BE ABLE TO DRIFT APART").

| element                   | declared by                          | Textual            | Qt                   |
|---------------------------|--------------------------------------|--------------------|----------------------|
| channel / thread line     | `TargetLine.menu_entries`            | `CommsRow`         | `ConversationRow`    |
| Comms relationship line   | `RelationshipLine.menu_entries`      | `RelationshipRow`  | `QtRelationshipItem` |
| open tab                  | `TabElement.menu_entries`            | `SessionLabel`     | `QtTabAt`            |
| history block             | `BlockMenu.block_commands`           | `Menu`             | `QtMenu`             |

A toolkit that built its own list instead fails here: it either calls an owner's
ingredients itself, defines the contract method, spells a declared entry, or its element
stops inheriting the declaring parent.
"""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "toad"
TOOLKITS = ("qt", "widgets", "screens")

# The ingredients of a declared menu: only its declaring owner calls them.
INGREDIENTS = {"standard_commands", "menu_entries_for_row", "pointer_menu", "tab_menu"}
# The contract method a toolkit element inherits and never defines.
CONTRACT = "menu_entries"
# Entries a declared menu spells; a toolkit spelling one is a parallel list.
DECLARED_LABELS = {"Open", "Copy name", "Move left", "Move right", "Close tab"}
# Each frontend element and the parent that declares its menu.
ELEMENTS = {
    ("widgets/sidebar_tree.py", "CommsRow"): "TargetLine",
    ("qt/window.py", "ConversationRow"): "TargetLine",
    ("widgets/thread_comms.py", "RelationshipRow"): "RelationshipLine",
    ("qt/thread_comms_panel.py", "QtRelationshipItem"): "RelationshipLine",
    ("widgets/session_tabs.py", "SessionLabel"): "TabElement",
    ("qt/window.py", "QtTabAt"): "TabElement",
    ("widgets/menu.py", "Menu"): "BlockMenu",
    ("qt/menu.py", "QtMenu"): "BlockMenu",
}


def toolkit_modules():
    for toolkit in TOOLKITS:
        for path in sorted((SOURCE / toolkit).rglob("*.py")):
            yield path, ast.parse(path.read_text(), str(path))


def called_name(call: ast.Call) -> str:
    function = call.func
    return function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")


def test_no_toolkit_assembles_a_declared_menu() -> None:
    found = [
        f"{path.relative_to(SOURCE)}:{node.lineno} calls {called_name(node)}"
        for path, tree in toolkit_modules()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and called_name(node) in INGREDIENTS
    ]
    assert not found, "a toolkit builds a menu its element's parent declares:\n" + "\n".join(found)


def test_no_toolkit_element_defines_the_menu_contract() -> None:
    found = [
        f"{path.relative_to(SOURCE)}:{node.lineno} {owner.name}.{CONTRACT}"
        for path, tree in toolkit_modules()
        for owner in ast.walk(tree) if isinstance(owner, ast.ClassDef)
        for node in owner.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == CONTRACT
    ]
    assert not found, "a toolkit element overrides its declared menu:\n" + "\n".join(found)


def test_no_toolkit_spells_a_declared_entry() -> None:
    found = [
        f"{path.relative_to(SOURCE)}:{node.lineno} {node.value!r}"
        for path, tree in toolkit_modules()
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and called_name(call) == "MenuEntry"
        for node in ast.walk(call)
        if isinstance(node, ast.Constant) and node.value in DECLARED_LABELS
    ]
    assert not found, "a toolkit spells an entry a shared parent declares:\n" + "\n".join(found)


def test_every_element_inherits_its_declared_menu() -> None:
    missing = []
    for (module, name), parent in ELEMENTS.items():
        tree = ast.parse((SOURCE / module).read_text())
        cls = next((node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == name), None)
        bases = {getattr(base, "id", getattr(base, "attr", "")) for base in (cls.bases if cls else ())}
        if cls is None or parent not in bases | indirect_bases(tree, bases):
            missing.append(f"{module}:{name} does not inherit {parent}")
    assert not missing, "\n".join(missing)


def indirect_bases(tree: ast.Module, bases: set[str]) -> set[str]:
    """Bases of bases declared in the same module (CommsRow's subclasses inherit through it)."""
    classes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    seen, pending = set(), list(bases)
    while pending:
        name = pending.pop()
        if name in seen or name not in classes:
            continue
        seen.add(name)
        pending.extend(getattr(base, "id", getattr(base, "attr", "")) for base in classes[name].bases)
    return {getattr(base, "id", getattr(base, "attr", ""))
            for name in seen for base in classes[name].bases}
