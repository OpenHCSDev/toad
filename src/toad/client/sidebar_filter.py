"""Shared sidebar-search filter state.

Both frontends' sidebars show a text input that narrows the channel / thread rows
to names matching the typed text. Before this owner existed Textual's `SideBar`
carried a `search: reactive("")` attribute and Qt had no filter at all, so the
two frontends disagreed by construction. This class is the single owner of the
match decision and the current text; Textual's `SideBar.search` reactive and
Qt's `QLineEdit` both write through it, and every listing (Textual's
`SidebarGroup.sync_members`, Qt's `Sidebar.draw_lines`)
reads through `matching` (which ranks what `matches`) instead of comparing text itself. A new frontend never
reimplements the match rule; it hands the filter a row name and asks.

The class is toolkit-neutral (no Textual, no Qt, no reactive); subscribers are a
plain callable list so the Qt side can repaint and the Textual side can bridge
the shared owner to its reactive watchers.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Iterable

from metaclass_registry import AbstractHooksMeta


class SidebarFilter:
    """Owns the current sidebar search text and the row-match decision. Instances
    are per-sidebar, not global: a frontend that shows two sidebars gives each
    its own filter so typing in one does not narrow the other.
    """

    def __init__(self) -> None:
        self._text: str = ""
        self._subscribers: list[Callable[[str], None]] = []

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        normalized = value or ""
        if normalized == self._text:
            return
        self._text = normalized
        for subscriber in tuple(self._subscribers):
            subscriber(normalized)

    def clear(self) -> None:
        self.text = ""

    def subscribe(self, callback: Callable[[str], None]) -> None:
        """Called with the new text whenever `text` changes; also implicitly whenever
        a frontend repaints (callers may pull `text` directly for that path). A fresh
        subscriber is NOT called with the current text — the caller knows what state
        it started from. The list is a plain list so unsubscribing (if ever needed)
        is just `_subscribers.remove(callback)`; no listener carries weak refs because
        subscriber lifetimes match the sidebar's."""
        self._subscribers.append(callback)

    def matches(self, name: str) -> bool:
        """The one match decision. Both frontends ask this question of the filter
        instead of comparing text themselves. Case-insensitive substring; an empty
        filter matches everything."""
        if not self._text:
            return True
        return self._text.casefold() in name.casefold()

    def matching[T](self, items: Iterable[T], name: Callable[[T], str] = str) -> tuple[T, ...]:
        """The listing both frontends draw: the ``items`` whose ``name`` matches, the name
        typed exactly first, then names that start with it, then the rest, each in the
        order given. Typing `claude-a` puts the live `claude-a` above every `claude-a…`
        fork it is a prefix of."""
        listed = [item for item in items if self.matches(name(item))]
        if not self._text:
            return tuple(listed)
        typed = self._text.casefold()

        def rank(item: T) -> int:
            folded = name(item).casefold()
            return 0 if folded == typed else 1 if folded.startswith(typed) else 2

        return tuple(sorted(listed, key=rank))


class SidebarSearchField(metaclass=AbstractHooksMeta):
    """The sidebar's search input as a frontend draws it: Textual's `SidebarSearch` and Qt's
    `QtSidebarSearch` both inherit this. It says what it searches while empty, and clearing
    it (Escape on both) empties the field, whose text the sidebar's `SidebarFilter` follows."""

    search_placeholder = "Search"

    @abstractmethod
    def show_search(self, text: str) -> None:
        """Put ``text`` in the field."""

    def clear_search(self) -> None:
        self.show_search("")
