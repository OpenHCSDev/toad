"""Visible conversation feedback from the core's current thread presentation."""
from agent_comms.mro_dispatch import handles
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from toad.core import events as core_events

import asyncio
from collections.abc import Awaitable, Callable

from toad.screens.session_view import SessionView
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.coordination_errors import CoordinationReadUnavailable
from textual.message import Message
from textual.widgets import Static


class ObservedThreadActivity(CoreEventReceiver, Static):
    """Observation never starts/settles an ACP turn or changes send admission."""

    DEFAULT_CSS = """
    ObservedThreadActivity { height: auto; color: $text-muted; }
    ObservedThreadActivity.-working { color: $accent; }
    ObservedThreadActivity.-unavailable { color: $warning; }
    """

    class Changed(Message):
        def __init__(self, observation, read, presentation: ThreadPresentation | None, unavailable: bool):
            super().__init__()
            self.observation, self.read = observation, read
            self.presentation = presentation
            self.unavailable = unavailable

        @property
        def current(self) -> bool:
            return self.read is self.observation.read

    def __init__(self, read: Callable[[], Awaitable[ThreadPresentation | None]]):
        super().__init__("", markup=False)
        self.display = False
        self.read = read
        self.presentation: ThreadPresentation | None = None
        self.unavailable = False
        self._read_task: asyncio.Task[None] | None = None
        self._pending_reads: asyncio.Queue[
            Callable[[], Awaitable[ThreadPresentation | None]]
        ] = asyncio.Queue(maxsize=1)

    def on_mount(self) -> None:
        # The shared coordination observer already owns source revision and
        # expiry. Rebuilding the same proof on a second cadence burns CPU and
        # competes with the original receipt/read transactions.
        self.observe_core(self.app.coordination_access.events)
        self.observe_core(self.app.events)
        self.refresh_observation()

    def bind(self, read: Callable[[], Awaitable[ThreadPresentation | None]]) -> None:
        """Retire the old read and its paint before a shared view changes source."""
        if self._read_task is not None:
            self._read_task.cancel()
        self._read_task = None
        if not self._pending_reads.empty():
            self._pending_reads.get_nowait()
        self.read = read
        self._publish(None, False)
        self.refresh_observation()

    def on_unmount(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()

    @handles(core_events.SessionSelected, core_events.ThreadActionsChanged, core_events.CoordinationObserved)
    async def app_observed(self, event: CoreEventMessage) -> None:
        self.refresh_observation()

    def refresh_observation(self, _event=None) -> None:
        if not self.is_attached or not self.query_ancestor(SessionView).is_current:
            return
        # Keep the latest original read request while the acquired read joins.
        # This is a one-slot rendering resource, never a readiness/owner cache.
        if self._pending_reads.full():
            self._pending_reads.get_nowait()
        self._pending_reads.put_nowait(self.read)
        if self._read_task is None or self._read_task.done():
            self._read_task = asyncio.create_task(self._observe())

    async def _observe(self) -> None:
        while not self._pending_reads.empty():
            read = self._pending_reads.get_nowait()
            try:
                presentation, unavailable = await read(), False
            except CoordinationReadUnavailable:
                if read is self.read and self.is_attached:
                    if self._pending_reads.empty():
                        self._pending_reads.put_nowait(read)
                    self._publish(self.presentation, True)
                # The original coordination observer resumes this same read;
                # a busy snapshot supplies neither absence nor fresh status.
                return
            except Exception:
                presentation, unavailable = None, True
            if (read is not self.read or not self.is_attached
                    or not self.query_ancestor(SessionView).is_current):
                return
            self._publish(presentation, unavailable)

    def _publish(self, presentation, unavailable) -> None:
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
        self.post_message(self.Changed(self, self.read, presentation, unavailable))
