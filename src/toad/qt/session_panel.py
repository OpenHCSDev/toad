"""Qt's thread-sidebar panel base: Textual's `SessionPanel` family's sibling.

Both inherit `ThreadSidebarPanelBody` (the roster entry a panel names). This base adds the
Qt panels' one view binding.

Every panel that renders per-view state (category filter, context explorer, plan,
thread-comms panel) carried the same three lines independently: `self._view = None`,
`def bind(view): self._view = view; self.present()`. Factored here once so the
bind/present contract has one owner. Mixed into each panel's bases alongside its
QWidget-derived base (not inheriting QWidget itself so each concrete panel keeps
its existing metaclass without conflict, matching how `SessionScope` in
`toad.client.session_scope` is also a plain mixin for the same reason).
"""
from __future__ import annotations

from toad.client.session_scope import NoConversationView, SessionScope
from toad.thread_sidebar_declarations import ThreadSidebarPanelBody


class SessionPanel(ThreadSidebarPanelBody):
    """Qt sidebar panel bound to the active conversation view.

    `_view` is the one owner of "which view this panel follows": a conversation, or the
    welcome's `NoConversationView` answers, never None. `bind(view)` updates it and triggers
    a `present()`. Concrete panels override `present()`
    to read from `self._view` and repaint. Panels that need additional bind-time
    work (subscriptions, refetches) extend `bind` with `super().bind(view)` then
    their own logic.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._view: SessionScope = NoConversationView()

    def bind(self, view: SessionScope) -> None:
        """Follow ``view``; `present()` paints its state at once."""
        self._view = view
        self.present()

    def present(self) -> None:
        """Repaint from `self._view`. Concrete panels override."""
