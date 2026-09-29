"""Request-bound terminal attention; title states own their actual timer lifetime."""

from __future__ import annotations

from abc import abstractmethod
from functools import cached_property, partial
import os
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from textual.content import Content
from textual.notifications import Notification
from textual.widget import Widget

if TYPE_CHECKING:
    from toad.app import ToadApp


class TitleFrame(DeclaredFamily, affix="TitleFrame"):
    @abstractmethod
    def icon(self, attention: TerminalAttention) -> str: ...

    @abstractmethod
    def next(self) -> TitleFrame: ...


class IconTitleFrame(TitleFrame):
    def icon(self, attention: TerminalAttention) -> str:
        return attention.icon

    def next(self) -> TitleFrame:
        return PointerTitleFrame()


class PointerTitleFrame(TitleFrame):
    def icon(self, attention: TerminalAttention) -> str:
        return "👉"

    def next(self) -> TitleFrame:
        return IconTitleFrame()


class TerminalTitle(DeclaredFamily, affix="TerminalTitle"):
    def __init__(self, attention: TerminalAttention) -> None:
        self.attention = attention

    @abstractmethod
    def reconcile(self) -> TerminalTitle: ...

    @abstractmethod
    def icon(self) -> str: ...

    def close(self) -> None:
        pass

    def publish(self) -> None:
        attention = self.attention
        selected = attention.app.selected_session
        screen_title = selected.title if selected is not None else attention.app.screen.title
        title = f"{attention.title} — {screen_title}" if screen_title else attention.title
        if driver := attention.app._driver:
            driver.write(f"\033]0;{self.icon()} {title}\007")


class DetachedTerminalTitle(TerminalTitle):
    """Settings may change before App mount or while its screens are retiring."""
    def reconcile(self) -> TerminalTitle:
        return self

    def icon(self) -> str:
        return self.attention.icon

    def publish(self) -> None:
        pass


class QuietTerminalTitle(TerminalTitle):
    def reconcile(self) -> TerminalTitle:
        return BlinkingTerminalTitle(self.attention) if self.attention.flashing_enabled else self

    def icon(self) -> str:
        return self.attention.icon


class BlinkingTerminalTitle(TerminalTitle):
    def __init__(self, attention: TerminalAttention) -> None:
        super().__init__(attention)
        self.frame: TitleFrame = PointerTitleFrame()
        self.timer = attention.app.set_interval(.5, self.advance)

    def reconcile(self) -> TerminalTitle:
        if self.attention.flashing_enabled:
            return self
        self.close()
        return QuietTerminalTitle(self.attention)

    def advance(self) -> None:
        self.frame = self.frame.next()
        self.attention.update()

    def icon(self) -> str:
        return self.frame.icon(self.attention)

    def close(self) -> None:
        self.timer.stop()


class TerminalAttention:
    title = "Toad"
    icon = "🐸"

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.sources: set[Widget] = set()
        self.state: TerminalTitle = DetachedTerminalTitle(self)

    @property
    def flashing_enabled(self) -> bool:
        return bool(self.sources) and self.app.settings.notifications.blink_title

    def require(self, source: Widget) -> None:
        """One live request source contributes once, even with queued questions."""
        self.sources.add(source)
        self.update()

    def release(self, source: Widget) -> None:
        self.sources.discard(source)
        self.update()

    def update(self) -> None:
        self.state = self.state.reconcile()
        self.state.publish()

    def attach(self) -> None:
        self.state.close()
        self.state = QuietTerminalTitle(self)
        self.update()

    def close(self) -> None:
        self.sources.clear()
        self.state.close()
        self.state = DetachedTerminalTitle(self)

    def notify(self, message: str, *, title: str = "", sound: str | None = None) -> None:
        """Dispatch the existing declared desktop policy on Textual's worker."""
        policy = self.app.settings.notifications.system
        self.app.run_worker(partial(policy.deliver, self.app, message, title=title, sound=sound),
                            thread=True, exit_on_error=False)

    def notification(self, notification: Notification) -> None:
        settings = self.app.settings.notifications
        if settings.hide_low_severity and notification.severity == "information":
            return
        message = (Content.from_markup(notification.message).plain
                   if notification.markup else notification.message)
        self.notify(message, title=notification.title)

    @cached_property
    def program(self) -> str:
        """Decode the terminal's external environment once."""
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
