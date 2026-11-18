"""Input-required attention, owned once for both frontends.

While something waits on the reader (a question, a permission request), the app's title
blinks between the app's icon and a pointer, if `notifications.blink_title` allows it.
Which requests are live, whether the title blinks, and its frames live here; a frontend
says only where the title goes (`publish_title`): Textual's terminal title, Qt's window
title. The blink's timer is the host's `repeat_ui`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_comms.nominal.declared_family import DeclaredFamily


class TitleFrame(DeclaredFamily, affix="TitleFrame"):
    @abstractmethod
    def icon(self, attention: InputAttention) -> str: ...

    @abstractmethod
    def next(self) -> TitleFrame: ...


class IconTitleFrame(TitleFrame):
    def icon(self, attention: InputAttention) -> str:
        return attention.icon

    def next(self) -> TitleFrame:
        return PointerTitleFrame()


class PointerTitleFrame(TitleFrame):
    def icon(self, attention: InputAttention) -> str:
        return "👉"

    def next(self) -> TitleFrame:
        return IconTitleFrame()


class AttentionTitle(DeclaredFamily, affix="AttentionTitle"):
    """The title's state: its timer lives exactly as long as the blinking state does."""

    def __init__(self, attention: InputAttention) -> None:
        self.attention = attention

    @abstractmethod
    def reconcile(self) -> AttentionTitle: ...

    @abstractmethod
    def icon(self) -> str: ...

    def close(self) -> None:
        """Only the blinking state holds a timer to stop."""

    def publish(self) -> None:
        self.attention.publish_title(self.icon())


class DetachedAttentionTitle(AttentionTitle):
    """Settings may change before the app shows its window or while it closes: nothing
    to title yet."""

    def reconcile(self) -> AttentionTitle:
        return self

    def icon(self) -> str:
        return self.attention.icon

    def publish(self) -> None:
        """No title is shown yet to write."""


class QuietAttentionTitle(AttentionTitle):
    def reconcile(self) -> AttentionTitle:
        return BlinkingAttentionTitle(self.attention) if self.attention.flashing_enabled else self

    def icon(self) -> str:
        return self.attention.icon


class BlinkingAttentionTitle(AttentionTitle):
    def __init__(self, attention: InputAttention) -> None:
        super().__init__(attention)
        self.frame: TitleFrame = PointerTitleFrame()
        self.timer = attention.app.repeat_ui(.5, self.advance)

    def reconcile(self) -> AttentionTitle:
        if self.attention.flashing_enabled:
            return self
        self.close()
        return QuietAttentionTitle(self.attention)

    def advance(self) -> None:
        self.frame = self.frame.next()
        self.attention.update()

    def icon(self) -> str:
        return self.frame.icon(self.attention)

    def close(self) -> None:
        self.timer.stop()


class InputAttention(ABC):
    """The live input requests and the title they blink; `update` re-derives the title
    from both and from `notifications.blink_title` (that setting's effect)."""

    title = "Toad"
    icon = "🐸"

    def __init__(self, app) -> None:
        self.app = app
        self.sources: set[object] = set()
        self.state: AttentionTitle = DetachedAttentionTitle(self)

    @property
    def flashing_enabled(self) -> bool:
        return bool(self.sources) and self.app.settings.notifications.blink_title

    def require(self, source: object) -> None:
        """One live request source contributes once, even with queued questions."""
        self.sources.add(source)
        self.update()

    def release(self, source: object) -> None:
        self.sources.discard(source)
        self.update()

    def update(self) -> None:
        self.state = self.state.reconcile()
        self.state.publish()

    def attach(self) -> None:
        """The app's title is shown: draw it from now on."""
        self.state.close()
        self.state = QuietAttentionTitle(self)
        self.update()

    def close(self) -> None:
        self.sources.clear()
        self.state.close()
        self.state = DetachedAttentionTitle(self)

    @abstractmethod
    def publish_title(self, icon: str) -> None:
        """Show the app's title led by ``icon`` where this frontend shows it."""
