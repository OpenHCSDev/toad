"""Visible conversation feedback from the core's current thread presentation."""

import asyncio
from collections.abc import Awaitable, Callable

from agent_comms.owner_lifecycle import OBSERVATION_INTERVAL
from agent_comms.thread_presentation import ThreadPresentation
from textual.message import Message
from textual.widgets import Static


class ObservedThreadActivity(Static):
    """Observation never starts/settles an ACP turn or changes send admission."""

    DEFAULT_CSS = """
    ObservedThreadActivity { height: auto; color: $text-muted; }
    ObservedThreadActivity.-working { color: $accent; }
    ObservedThreadActivity.-unavailable { color: $warning; }
    """

    class Changed(Message):
        def __init__(self, presentation: ThreadPresentation | None, unavailable: bool):
            super().__init__()
            self.presentation = presentation
            self.unavailable = unavailable

    def __init__(self, read: Callable[[], Awaitable[ThreadPresentation | None]]):
        super().__init__("", markup=False)
        self.display = False
        self.read = read
        self.presentation: ThreadPresentation | None = None
        self.unavailable = False
        self._read_task: asyncio.Task[None] | None = None

    def on_mount(self) -> None:
        self.set_interval(OBSERVATION_INTERVAL, self.refresh_observation)
        self.refresh_observation()

    def refresh_observation(self) -> None:
        if (not self.is_attached or self.screen is not self.app.screen
                or self._read_task is not None and not self._read_task.done()):
            return
        self._read_task = asyncio.create_task(self._observe())

    async def _observe(self) -> None:
        try:
            presentation, unavailable = await self.read(), False
        except Exception:
            presentation, unavailable = None, True
        if not self.is_attached or self.screen is not self.app.screen:
            return
        if (presentation, unavailable) == (self.presentation, self.unavailable):
            return
        self.presentation, self.unavailable = presentation, unavailable
        self.display = presentation is not None or unavailable
        self.update("Agent status unavailable" if unavailable else
                    presentation.summary if presentation else "")
        self.set_class(bool(presentation and presentation.busy), "-working")
        self.set_class(unavailable, "-unavailable")
        self.post_message(self.Changed(presentation, unavailable))
