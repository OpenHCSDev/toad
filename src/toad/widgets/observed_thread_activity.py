"""Visible conversation feedback from the core's current thread presentation."""

import asyncio
from collections.abc import Awaitable, Callable

from toad.constants import COMMS_REFRESH_INTERVAL
from toad.screens.session_view import SessionView
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
        self.set_interval(COMMS_REFRESH_INTERVAL, self.refresh_observation)
        self.refresh_observation()

    def refresh_observation(self) -> None:
        if (not self.is_attached or not self.query_ancestor(SessionView).is_current
                or self._read_task is not None and not self._read_task.done()):
            return
        self._read_task = asyncio.create_task(self._observe())

    async def _observe(self) -> None:
        try:
            presentation, unavailable = await self.read(), False
        except Exception:
            presentation, unavailable = None, True
        if not self.is_attached or not self.query_ancestor(SessionView).is_current:
            return
        if (presentation, unavailable) == (self.presentation, self.unavailable):
            return
        self.presentation, self.unavailable = presentation, unavailable
        self.display = presentation is not None or unavailable
        lines = ["Agent status unavailable" if unavailable else
                 presentation.summary if presentation else ""]
        if presentation is not None and presentation.notifications:
            lines.append("Recent incoming messages:")
            for receipt in presentation.notifications:
                message = receipt.message
                if message is None:
                    continue
                excerpt = " ".join(message.body.split())
                if len(excerpt) > 110:
                    excerpt = excerpt[:107] + "…"
                lines.append(f"{message.target} · {message.sender}: {excerpt} — {receipt.state}")
        self.update("\n".join(lines))
        self.set_class(bool(presentation and presentation.busy), "-working")
        self.set_class(unavailable or bool(presentation and presentation.attention), "-unavailable")
        self.post_message(self.Changed(presentation, unavailable))
