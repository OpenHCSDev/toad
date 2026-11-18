"""Fail when a Qt class re-implements a frontend-neutral or Textual sibling instead of inheriting it.

A Qt class `QtFoo` (or `Foo`) under toad.qt whose same-named sibling `Foo` lives elsewhere in toad
must share a toolkit-neutral toad ancestor with it — the behaviour lives once, on that ancestor,
and the Qt class adds only toolkit calls. A pair sharing nothing is a hand-rolled parallel copy.

KNOWN_COPIES is the debt on main when this ratchet landed. It only shrinks:
  - a NEW copy (not listed) fails: hoist the shared behaviour and inherit it instead;
  - a listed copy that now shares an ancestor also fails until you delete its line here.
Run with an interpreter that has PySide6 (the agent-comms runtime):
  QT_QPA_PLATFORM=offscreen PYTHONPATH=src <runtime>/bin/python tools/qt_inherit_ratchet.py
Every Qt PR pastes this tool's output.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys

KNOWN_COPIES = {
    "toad.qt.keymap_screen.QtKeymapScreen": "toad.screens.keymap.KeymapScreen",
    "toad.qt.menu.QtMenu": "toad.widgets.menu.Menu",
    "toad.qt.settings_screen.QtBoolEditor": "toad.forms.editors.BoolEditor",
    "toad.qt.settings_screen.QtChoicesEditor": "toad.forms.editors.ChoicesEditor",
    "toad.qt.settings_screen.QtFloatEditor": "toad.forms.editors.FloatEditor",
    "toad.qt.settings_screen.QtIntEditor": "toad.forms.editors.IntEditor",
    "toad.qt.settings_screen.QtSettingsScreen": "toad.screens.settings.SettingsScreen",
    "toad.qt.settings_screen.QtStrEditor": "toad.forms.editors.StrEditor",
    "toad.qt.transfer.QtThreadImportDialog": "toad.widgets.comms_transfer.ThreadImportDialog",
    "toad.qt.transfer.QtTransferDialog": "toad.widgets.comms_transfer.TransferDialog",
    "toad.qt.transfer.QtWireExportDialog": "toad.widgets.comms_transfer.WireExportDialog",
    "toad.qt.window.BusAddress": "toad.screens.bus_choice.BusAddress",
}

# Same name, different concept: not a frontend pair. Each entry says what the sibling really is.
NOT_SIBLINGS = {
    "toad.qt.plan_panel.QtPlan": "toad.core.events.Plan is Core's plan event, not a panel",
    "toad.qt.goal.QtGoalControl": "toad.slash_command.GoalControl is the /goal slash command, not a widget",
    "toad.qt.window.QtSessionEntry": "toad.client.session_entry.SessionEntry is the session record; QtSessionEntry is a SessionEntries member",
    "toad.qt.prompt_stack.QtFlash": "toad.messages.Flash is the Textual Message requesting a flash; the widget sibling toad.widgets.flash.Flash shares toad.client.prompt_stack.FlashNotice",
    "toad.qt.prompt_stack.QtSessionDetails": "toad.client.session_tracker.SessionDetails is the tab's session record; the widget sibling toad.widgets.session_details.SessionDetails shares ObservedActivity + SessionStatusTitle",
}

FRONTEND_PREFIXES = ("toad.qt", "toad.widgets", "toad.screens")


def neutral(cls: type) -> bool:
    """A toad class that belongs to neither frontend: where shared behaviour lives."""
    return cls.__module__.startswith("toad.") and not cls.__module__.startswith(FRONTEND_PREFIXES)


def classes_under(package_name: str) -> dict[str, type]:
    package = importlib.import_module(package_name)
    found: dict[str, type] = {}
    for info in pkgutil.walk_packages(package.__path__, package_name + "."):
        module = importlib.import_module(info.name)  # an import failure is a failure, never skipped
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__:
                found[f"{cls.__module__}.{cls.__qualname__}"] = cls
    return found


def copies() -> dict[str, str]:
    everything = classes_under("toad")
    siblings: dict[str, type] = {}
    for path, cls in everything.items():
        if not path.startswith("toad.qt."):
            siblings.setdefault(cls.__name__, cls)
    pairs: dict[str, str] = {}
    for path, cls in everything.items():
        if not path.startswith("toad.qt."):
            continue
        sibling = siblings.get(cls.__name__.removeprefix("Qt"))
        if sibling is None or path in NOT_SIBLINGS:
            continue
        if not any(neutral(ancestor) for ancestor in cls.__mro__ if ancestor in sibling.__mro__):
            pairs[path] = f"{sibling.__module__}.{sibling.__qualname__}"
    return pairs


def main() -> int:
    found = copies()
    new = sorted(set(found) - set(KNOWN_COPIES))
    fixed = sorted(set(KNOWN_COPIES) - set(found))
    for path in new:
        print(f"NEW COPY   {path} re-implements {found[path]}: hoist its behaviour to a shared ancestor and inherit it")
    for path in fixed:
        print(f"FIXED      {path} now shares an ancestor (or is gone): delete its KNOWN_COPIES line")
    print(f"parallel copies: {len(found)} (ratchet baseline {len(KNOWN_COPIES)})")
    return 1 if new or fixed else 0


if __name__ == "__main__":
    sys.exit(main())
