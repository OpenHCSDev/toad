"""Qt's input attention: the shared `InputAttention` drawn on the window title."""

from __future__ import annotations

from toad.client.input_attention import InputAttention


class QtWindowAttention(InputAttention):
    """The window title names the open tab, led by the app's icon, or by a blinking pointer
    while input is required and `notifications.blink_title` allows it."""

    def publish_title(self, icon: str) -> None:
        tabs = self.app.tabs
        tab = tabs.tabText(tabs.currentIndex()) if tabs.count() else ""
        title = f"{self.title} — {tab}" if tab else self.title
        self.app.setWindowTitle(f"{icon} {title}")
