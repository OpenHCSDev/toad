"""Saved sessions, including older/ambiguous identities, inside normal Comms."""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from typing import ClassVar

from agent_comms.comms import Comms
from agent_comms.coordination_errors import StaleRevision
from agent_comms.mro_dispatch import handles
from agent_comms.ui_model.observation import ReadTranscript, ReadRecordedNotifications
from toad.core_event_carrier import CoreEventMessage, CoreEventReceiver
from agent_comms.historical_views import HistoricalThread
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from toad.screens.modal import ModalScreen
from textual.widgets import Select, Static

from toad.screens.workspace import WorkspaceScreen
from toad.project_path_owner import ProjectPathOwner
from toad.widgets.history_anchor import HistoryWindow
from toad.widgets.conversation import Contents
from toad.widgets.transcript_history import TranscriptHistory


class RecordedContents(Contents):
    """The notification subscriber reads the same archive as its history."""

    def __init__(self, source: str, **kwargs):
        self.notification_request = partial(ReadRecordedNotifications, source=source)
        super().__init__(**kwargs)


class HistoricalSessions(CoreEventReceiver, ProjectPathOwner, WorkspaceScreen, ModalScreen):
    BINDINGS: ClassVar = [("escape", "close", "Back to chats")]
    DEFAULT_CSS = """
    HistoricalSessions { align: center middle; background: $background 60%; }
    HistoricalSessions > Vertical { width: 95%; height: 95%; background: $surface; border: solid $primary; }
    HistoricalSessions #source-label { height: auto; padding: 1; }
    HistoricalSessions HistoryWindow { height: 1fr; }
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

    @property
    def coordination_root(self) -> str:
        return str(self.comms.root)

    @property
    def project_root(self) -> Path:
        index = self.query_one("#saved-identity", Select).value
        return Path(self.threads[index].thread.worktree)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "Saved sessions · select an original identity · Esc returns to chats",
                id="source-label",
            )
            options = [
                (
                    (
                        f"@{item.thread.name} · {item.thread.display_title} · "
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
            with HistoryWindow(id="saved-window"):
                yield Contents(id="saved-content")

    @on(Select.Changed, "#saved-identity")
    @work(exclusive=True, group="historical-selection")
    async def selected(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self._selection_generation += 1
        self.workers.cancel_group(self, "historical-handling")
        generation = self._selection_generation
        item = self.threads[event.value]
        previous = self.query_one("#saved-content", Contents)
        content = RecordedContents(item.source.key, id="saved-content")
        with self.app.batch_update():
            await previous.remove()
            await self.query_one("#saved-window", HistoryWindow).mount(content)
        self.query_one("#source-label", Static).update(
            f"@{item.thread.name} · original incarnation {item.thread.created_at}\n"
            f"Source: {item.source.original_root}\n"
            f"Channels/tags: {', '.join(sorted(item.thread.tags)) or 'none'}\n"
            f"Session: {item.thread.session_file or 'No saved session recorded'} · read only"
        )
        access, root = self.app.coordination_access, str(self.comms.root)

        async def load(**kwargs):
            snapshot = await access.transcripts.read(ReadTranscript(
                root, item.thread.name, historical_source=item.source.key, **kwargs))
            return snapshot.page

        try:
            page = await load()
        except StaleRevision as error:
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
            from toad.transcript_preparation import SavedHistory, TranscriptPageRenderTask
            from toad.work_preparation import RenderPreparation

            prepared = await self.app.preparation.submit(RenderPreparation(TranscriptPageRenderTask(page)))
            if generation != self._selection_generation or not self.is_attached:
                return
            history = TranscriptHistory(prepared, SavedHistory(load, page.after, self.app.preparation),
                                        notification_view=content)
            window = self.query_one(HistoryWindow)
            window.anchor()
            await content.prepare_history(
                history, lambda: generation == self._selection_generation and self.is_attached,
                window=window,
            )
            if generation != self._selection_generation or not self.is_attached:
                return
            async with window.preserve_history(root=content):
                await content.mount(history)

    def action_focus_prompt(self) -> None:
        self.query_one(HistoryWindow).jump_to_latest()

    def action_close(self) -> None:
        self.dismiss()
