"""Text swept into the theme's colours by ui_theme's splash effect."""

from __future__ import annotations

from textual.content import Content
from textual.widgets import Static
from ui_theme.effects import PlayedText, TextFrame
from ui_theme.scheme import ColourScheme
from ui_theme.splash import loading_splash

from toad.frame_presentation import Animated
from toad.block_navigation import ConversationBlock


class SplashText(Animated[TextFrame], Static):
    """Shows ``TEXT`` plainly until its effect's frames arrive, then plays them.

    The frames are built in a render worker, once per colour scheme. A
    stopped effect leaves its last frame showing.
    """

    TEXT = ""

    played: PlayedText | None = None
    # The scheme `played` was built in.
    _scheme: ColourScheme | None = None

    def play(self) -> None:
        self.run_worker(self._play(), group="splash", exclusive=True)

    @property
    def plays(self) -> bool:
        """Whether the effect may run now; otherwise its last frame shows."""
        return self.is_attached

    async def _play(self) -> None:
        scheme = self.app.colours.scheme
        if self.played is None or self._scheme is not scheme:
            self.played = await self.app.colours.schemes[self.app.theme].palette.text_effect(
                self.app.colours, loading_splash(self.TEXT), scheme)
            self._scheme = scheme
        if self.plays:
            self.run_effect(self.played)
        elif self.is_attached:
            self.refresh()

    def render(self) -> Content:
        played = self.played
        if played is not None:
            return self.app.colours.paint_text(self.effect_frame(played), None)
        return Content(self.TEXT)


class ThreadLoading(ConversationBlock, SplashText):
    """The splash while a thread attaches: its label swept into the theme's colours."""

    LABEL = TEXT = "Loading thread and history…"

    @classmethod
    def initial_contents(cls, agent):
        """The loading declaration serves first composition and source rebinding."""
        return (cls(),) if agent is not None else ()

    DEFAULT_CSS = """
    ThreadLoading {
        width: 1fr;
        height: auto;
        margin: 0;
        content-align: center middle;
        color: $text-muted;
        text-style: bold;
    }
    """

    def on_mount(self) -> None:
        self.play()
