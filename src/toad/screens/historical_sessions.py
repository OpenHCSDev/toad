"""Saved sessions, including older/ambiguous identities, inside normal Comms."""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from typing import ClassVar

from agent_comms.comms import Comms
from agent_comms import HistoricalThread
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalGroup
from textual.screen import ModalScreen
from textual.widgets import Select, Static

from toad.screens.workspace import WorkspaceScreen
from toad.widgets.conversation import Window
from toad.widgets.transcript_history import TranscriptHistory


class HistoricalSessions(WorkspaceScreen, ModalScreen):
    BINDINGS: ClassVar = [("escape", "close", "Back to chats")]
    DEFAULT_CSS = """
    HistoricalSessions { align: center middle; background: $background 60%; }
    HistoricalSessions > Vertical { width: 95%; height: 95%; background: $surface; border: solid $primary; }
    HistoricalSessions #source-label { height: auto; padding: 1; }
    HistoricalSessions Window { height: 1fr; }
    HistoricalSessions #saved-content { height: auto; }
    """

    def __init__(
        self,
        comms: Comms,
        threads: tuple[HistoricalThread, ...],
        *,
        name: str | None = None,
        source: str | None = None,
    ):
        super().__init__()
        self.comms = comms
        self.threads = threads
        self.initial_name = name
        self.initial_source = source
        self._selection_generation = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "Saved sessions · select an original identity · Esc returns to chats",
                id="source-label",
            )
            options = [
                (
                    (
                        f"@{item.thread.name} · {item.thread.title or 'Untitled'} · "
                        f"{Path(item.source.original_root).name} · created {item.thread.created_at}"
                    ),
                    index,
                )
                for index, item in enumerate(self.threads)
            ]
            initial = next(
                (
                    index
                    for index, item in enumerate(self.threads)
                    if item.thread.name == self.initial_name
                    and (
                        self.initial_source is None
                        or item.source.key == self.initial_source
                    )
                ),
                0,
            )
            yield Select(options, allow_blank=False, value=initial, id="saved-identity")
            with Window():
                yield VerticalGroup(id="saved-content")

    @on(Select.Changed, "#saved-identity")
    async def selected(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self._selection_generation += 1
        generation = self._selection_generation
        item = self.threads[event.value]
        content = self.query_one("#saved-content", VerticalGroup)
        await content.remove_children()
        self.query_one("#source-label", Static).update(
            f"@{item.thread.name} · original incarnation {item.thread.created_at}\n"
            f"Source: {item.source.original_root}\n"
            f"Channels/tags: {', '.join(sorted(item.thread.tags)) or 'none'}\n"
            f"Session: {item.thread.session_file or 'No saved session recorded'} · read only"
        )
        loader = partial(
            self.comms.transcripts.thread_transcript_page,
            item.thread.name,
            historical_source=item.source.key,
        )

        async def load(**kwargs):
            return await asyncio.to_thread(loader, **kwargs)

        try:
            page = await load()
        except (OSError, ValueError) as error:
            if generation == self._selection_generation:
                await content.mount(
                    Static(f"Could not read this saved session: {error}", markup=False)
                )
            return
        if generation != self._selection_generation or not self.is_attached:
            return
        if not page.events and not page.has_older:
            await content.mount(
                Static("No saved conversation records are available for this identity.")
            )
        else:
            await content.mount(TranscriptHistory(page, load))
            self.query_one(Window).scroll_end(animate=False, immediate=True)

    def action_focus_prompt(self) -> None:
        self.query_one(Window).scroll_end(animate=False)

    def action_close(self) -> None:
        self.dismiss()
