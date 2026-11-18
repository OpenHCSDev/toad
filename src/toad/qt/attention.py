"""Qt's input attention: the shared `InputAttention` drawn on the window title."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from toad.client.input_attention import InputAttention


class QtWindowAttention(InputAttention):
    """The window title names the open tab, led by the app's icon, or by a blinking pointer
    while input is required and `notifications.blink_title` allows it."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.deliveries: set[asyncio.Task[None]] = set()

    def deliver(self, send: Callable[[], None]) -> None:
        """On the client's preparation thread; a failed delivery reaches the loop's handler."""
        task = asyncio.ensure_future(self.app.preparation.run_thread(send))
        self.deliveries.add(task)
        task.add_done_callback(self.delivered)

    def delivered(self, task: asyncio.Task[None]) -> None:
        self.deliveries.discard(task)
        task.result()

    def publish_title(self, icon: str) -> None:
        tabs = self.app.tabs
        tab = tabs.tabText(tabs.currentIndex()) if tabs.count() else ""
        title = f"{self.title} — {tab}" if tab else self.title
        self.app.setWindowTitle(f"{icon} {title}")
