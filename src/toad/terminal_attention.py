"""Textual's input attention: the shared `InputAttention` drawn on the terminal's title."""

from __future__ import annotations

from functools import partial
import os

from textual.content import Content
from textual.notifications import Notification

from toad.client.input_attention import InputAttention


class TerminalAttention(InputAttention):
    """Textual's input attention: the terminal's title, and desktop notifications."""

    def publish_title(self, icon: str) -> None:
        selected = self.app.selected_session
        screen_title = (selected.title
                        if self.app.current_mode == "workspace" and selected is not None
                        else self.app.screen.title)
        title = f"{self.title} — {screen_title}" if screen_title else self.title
        if driver := self.app._driver:
            driver.write(f"\033]0;{icon} {title}\007")

    def deliver(self, send) -> None:
        """On Textual's thread worker."""
        self.app.run_worker(send, thread=True)

    def notification(self, notification: Notification) -> None:
        settings = self.app.settings.notifications
        if settings.hide_low_severity and notification.severity == "information":
            return
        message = (Content.from_markup(notification.message).plain
                   if notification.markup else notification.message)
        self.notify(message, title=notification.title)

    @staticmethod
    def program() -> str:
        """Read terminal identity without constructing an application."""
        if program := os.environ.get("TERM_PROGRAM"):
            return program
        if "WT_SESSION" in os.environ:
            return "Windows Terminal"
        if "KITTY_WINDOW_ID" in os.environ:
            return "Kitty"
        if "ALACRITTY_SOCKET" in os.environ or "ALACRITTY_LOG" in os.environ:
            return "Alacritty"
        if "VTE_VERSION" in os.environ:
            return "VTE-based (GNOME Terminal/Tilix/etc.)"
        if "KONSOLE_VERSION" in os.environ:
            return "Konsole"
        return "Unknown"
