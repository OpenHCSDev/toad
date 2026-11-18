"""Reader actions every history window answers.

Declared where every reader imports them (Textual's `HistoryWindow`, Qt's
`QtHistoryWindow`). The `apply()` methods call the window by a method name both
backends implement (`action_page_down`, `action_page_up`, `jump_to_latest`), so each
backend binds the family's keys through its own binding mechanism — Textual through
the Action/BindingsMap path in `widget_actions`, Qt through `QShortcut` driven by
`toad.qt.action_shortcuts.ActionKeys.bind_family`.

`VimMode` is a Textual type used only as a dict key (mode marker). The import does not
fire Textual behaviour at load time, and both backends have Textual installed as a
dependency, so this module stays import-safe for the Qt path.
"""

from __future__ import annotations

from textual.document._editing import VimMode

from toad.history_jump import ReaderWindow
from toad.widget_actions import Action


class ReaderAction(Action, affix="Action"):
    """Vim reader keys every history window answers."""

    context_capability = ReaderWindow


class PageDownAction(ReaderAction, declared_name="reader_page_down"):
    """Move the reader one page toward the latest message."""

    keys = {VimMode: ("ctrl+d",)}

    def apply(self, window) -> None:
        window.action_page_down()


class PageUpAction(ReaderAction, declared_name="reader_page_up"):
    """Move the reader one page toward older history."""

    keys = {VimMode: ("ctrl+u",)}

    def apply(self, window) -> None:
        window.action_page_up()


class LatestAction(ReaderAction):
    """Follow the source tail, including pages outside the mounted window."""

    keys = {VimMode: ("G",)}

    def apply(self, window) -> None:
        window.jump_to_latest()
