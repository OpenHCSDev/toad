"""Native nodes bound to Toad's application contract."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from textual import events
from textual.dom import DOMNode
from textual import on
from toad.settings_scope import SettingsReader

if TYPE_CHECKING:
    from toad.app import ToadApp


class AppScoped:
    """Carries a `ToadApp` reference as ``self.app``: a plain mixin with no toolkit base, so
    Qt widgets can declare the same application-refinement type ``ToadNode`` gives Textual
    widgets, without dragging DOMNode into the Qt metaclass's MRO.
    """

    app: ToadApp


class ToadNode(AppScoped, SettingsReader):
    """Keep the application refinement on one shared native Textual parent."""


class FollowsTheme(DOMNode):
    """Redraws when the app's theme changes; each member says how in theme_changed."""

    @on(events.Mount)
    def _on_mount(self, event: events.Mount) -> None:
        # Textual dispatches each class's handler; the signal's theme is read from the app.
        self.app.theme_changed_signal.subscribe(
            self, lambda _theme: self.theme_changed()
        )

    @abstractmethod
    def theme_changed(self) -> None: ...
