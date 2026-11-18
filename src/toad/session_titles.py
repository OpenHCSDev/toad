"""How an agent session's tab gets its name, for every frontend.

A session is named by its user or agent (`SessionTitleChanged`), by the title its thread
presents (`SessionThreadTitle`), or, until either arrives, by a guess from its first prompt.
Textual's `MainScreen` and Qt's ACP session view both own one session's tab and inherit
these answers; each says only which session it names.
"""

from __future__ import annotations

from abc import abstractmethod

from metaclass_registry.mro_dispatch import MroDispatch, handles

from toad.core import events as core_events
from toad.core.events import SessionChangedEvent

AUTO_SESSION_TITLE_MAX_LENGTH = 50


def make_session_title(prompt: str) -> str:
    """Create a compact deterministic title from a session's first prompt."""
    title = " ".join(prompt.split())
    if len(title) > AUTO_SESSION_TITLE_MAX_LENGTH:
        title = title[: AUTO_SESSION_TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return title


class SessionTitles(MroDispatch):
    """The tab of one agent session follows the names its session is given."""

    @property
    @abstractmethod
    def named_session(self):
        """The `SessionDetails` this view names, or None while it has no tab yet."""

    @handles(core_events.SessionTitleChanged)
    def on_session_title_changed(self, event: core_events.SessionTitleChanged) -> None:
        """The user or the agent process named this session; the tab keeps it."""
        if (details := self.named_session) is not None:
            self.app.session_tracker.name_session(details.identity, event.name)

    @handles(core_events.SessionThreadTitle)
    def on_session_thread_title(self, event: core_events.SessionThreadTitle) -> None:
        """The thread presented a title; an authored name keeps the tab's label."""
        if (named := self.named_session) is None:
            return
        tracker = self.app.session_tracker
        if (details := tracker.get_session(named.identity)) is not None:
            if details.update_thread_title(event.title):
                tracker.events.publish(SessionChangedEvent(named.identity))

    @handles(core_events.SessionSubtitleChanged)
    def on_session_subtitle_changed(self, event: core_events.SessionSubtitleChanged) -> None:
        if (details := self.named_session) is not None:
            self.app.session_tracker.update_session(details.identity, subtitle=event.subtitle)


class FirstPromptTitle:
    """A conversation guesses its session's title from its first prompt, until the thread
    presents its own (a plain mixin beside each toolkit's base)."""

    _auto_title_eligible: bool = False

    async def auto_name_from_prompt(self, prompt: str) -> None:
        """A guess from the first prompt stands in until the thread presents its own title.

        It is not the user's label and not the thread's name: publishing it as an
        authored title made every later presented title lose, and naming the
        coordination thread after a prompt left sessions stuck under a guess long
        after they had moved on.
        """
        if not self._auto_title_eligible or self._agent_session_id.bound:
            return
        self._auto_title_eligible = False
        if not self.agent_binding.automatic_titles:
            return
        self.publish_core(core_events.SessionThreadTitle(make_session_title(prompt)))
