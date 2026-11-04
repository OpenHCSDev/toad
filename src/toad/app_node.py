"""Native nodes bound to Toad's application contract."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from textual import events
from textual.dom import DOMNode

if TYPE_CHECKING:
    from toad.app import ToadApp


class ToadNode(DOMNode):
    """Keep the application refinement on one shared native parent."""

    app: ToadApp


class FollowsTheme(DOMNode):
    """Redraws when the app's theme changes; each member says how in theme_changed."""

    def _on_mount(self, event: events.Mount) -> None:
        # Textual dispatches each class's handler; the signal's theme is read from the app.
        self.app.theme_changed_signal.subscribe(
            self, lambda _theme: self.theme_changed()
        )

    @abstractmethod
    def theme_changed(self) -> None: ...
