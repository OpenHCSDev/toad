"""Preference choices own their effects and external presentation values."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from agent_comms.declared_family import DeclaredFamily


class Choice(ABC):
    title: ClassVar[str | None] = None

    @classmethod
    def label(cls) -> str:
        return (
            cls.title or cls.declared_name.replace("-", " ").replace("_", " ").title()
        )


class Expansion(Choice, DeclaredFamily, affix="Expansion"):
    patch_preview = True

    @classmethod
    @abstractmethod
    def should_expand(cls, status) -> bool: ...


class NeverExpansion(Expansion):
    patch_preview = False

    @classmethod
    def should_expand(cls, status) -> bool:
        return False


class AlwaysExpansion(Expansion):
    @classmethod
    def should_expand(cls, status) -> bool:
        return True


class SuccessExpansion(Expansion):
    title = "Success only"

    @classmethod
    def should_expand(cls, status) -> bool:
        return status.completed


class FailExpansion(Expansion):
    title = "Fail only"

    @classmethod
    def should_expand(cls, status) -> bool:
        return status.failed


class BothExpansion(SuccessExpansion, FailExpansion):
    title = "Fail and success"

    @classmethod
    def should_expand(cls, status) -> bool:
        return SuccessExpansion.should_expand(status) or FailExpansion.should_expand(
            status
        )


class SessionBar(Choice, DeclaredFamily, affix="SessionBar"):
    @classmethod
    @abstractmethod
    def shown(cls, count: int) -> bool: ...


class AlwaysSessionBar(SessionBar):
    @classmethod
    def shown(cls, count: int) -> bool:
        return True


class MultipleSessionBar(SessionBar):
    title = "When there are multiple sessions"

    @classmethod
    def shown(cls, count: int) -> bool:
        return count > 1


class NeverSessionBar(SessionBar):
    @classmethod
    def shown(cls, count: int) -> bool:
        return False


class NotificationPolicy(Choice, DeclaredFamily, affix="Notification"):
    @classmethod
    def deliver(cls, app, message: str, *, title: str = "", sound: str | None = None) -> None:
        """Shared delivery belongs to the policy that admits it."""
        if not cls.enabled(app.app_focus):
            return
        from importlib.resources import files
        from notifypy import Notify
        import toad

        notification = Notify()
        notification.message = message
        notification.title = title
        notification.application_name = "🐸 Toad" if toad.os == "macos" else "Toad"
        if sound and app.settings.notifications.enable_sounds:
            notification.audio = str(files("toad.data").joinpath(f"sounds/{sound}.wav"))
        notification.icon = str(files("toad.data").joinpath("images/frog.png"))
        notification.send()

    @classmethod
    @abstractmethod
    def enabled(cls, focused: bool) -> bool: ...


class NeverNotification(NotificationPolicy):
    @classmethod
    def enabled(cls, focused: bool) -> bool:
        return False


class BlurNotification(NotificationPolicy):
    title = "When app is not focused"

    @classmethod
    def enabled(cls, focused: bool) -> bool:
        return not focused


class AlwaysNotification(NotificationPolicy):
    @classmethod
    def enabled(cls, focused: bool) -> bool:
        return True


class DiffMode(Choice, DeclaredFamily, affix="Diff"):
    split = False
    auto_split = False


class UnifiedDiff(DiffMode):
    pass


class SplitDiff(DiffMode):
    split = True


class AutoDiff(DiffMode):
    title = "Best fit"
    auto_split = True


class WrapMode(Choice, DeclaredFamily, affix="Mode"):
    enabled = False


class NoWrapMode(WrapMode, declared_name="no-wrap"):
    title = "Don't wrap"


class WrapModeEnabled(WrapMode, declared_name="wrap"):
    title = "Wrap long lines"
    enabled = True


class Scrollbar(Choice, DeclaredFamily, affix="Scrollbar"):
    """Spelling is the Textual reactive/CSS value, declared once by each member."""


class NormalScrollbar(Scrollbar):
    pass


class ThinScrollbar(Scrollbar):
    pass


class HiddenScrollbar(Scrollbar):
    pass


class LoadingStyle(Choice, DeclaredFamily, affix="Loading"):
    @classmethod
    @abstractmethod
    def widget(cls, screen): ...


class PulseLoading(LoadingStyle):
    @classmethod
    def widget(cls, screen):
        from textual.screen import Screen

        return Screen.get_loading_widget(screen)


class QuotesLoading(LoadingStyle):
    @classmethod
    def widget(cls, screen):
        import random

        from textual.content import Content

        from toad.app import QUOTES
        from toad.widgets.future_text import FutureText

        quotes = QUOTES.copy()
        random.shuffle(quotes)
        return FutureText([Content(quote) for quote in quotes])

