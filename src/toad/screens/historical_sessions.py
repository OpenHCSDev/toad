"""Saved sessions, including older/ambiguous identities, inside normal Comms."""

from __future__ import annotations



import asyncio
from functools import partial
from pathlib import Path

from agent_comms.coordination_errors import StaleRevision
from metaclass_registry.mro_dispatch import handles
from agent_comms.notification_reads import RecordedNotificationRead
from agent_comms.order_tools import TranscriptPageRead
from agent_comms.ui_model.observation import ReadTranscript
from toad.core_event_carrier import CoreEventMessage, CoreEventReceiver
from agent_comms.historical_views import HistoricalThread, HistorySourceKey
from agent_comms.transcripts import RecordedPageSource
from textual import on, work
from textual.app import ComposeResult
from toad.screens.modal import DismissibleScreen, ModalPanel
from textual.widgets import Select, Static

from toad.screens.workspace import WorkspaceFrame
from toad.widget_view import CenteredView
from toad.project_path_owner import ProjectPathOwner
from toad.widgets.history_anchor import HistoryWindow
from toad.widgets.conversation import Contents
from toad.transcript_state import LiveTranscript
from toad.widgets.transcript_history import LineHistory
from toad.comms_root import Observing


class RecordedContents(Contents):
    """The notification subscriber reads the same archive as its history."""

    def __init__(self, source: HistorySourceKey, **kwargs):
        self.notification_operation = partial(RecordedNotificationRead, source=source)
        super().__init__(**kwargs)


class SourceLabel(Static):
    """Which saved identity the window shows, and where it came from."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = 1


class HistoricalSessions(CenteredView, CoreEventReceiver, ProjectPathOwner, WorkspaceFrame, DismissibleScreen):

    def __init__(
        self,
        observed: Observing,
        threads: tuple[HistoricalThread, ...],
        *,
        name: str | None = None,
        source: str | None = None,
    ):
        super().__init__()
        self.observed = observed
        self.threads = threads
        self.initial_name = name
        self.initial_source = source
        self._selection_generation = 0

    @property
    def coordination_root(self) -> str:
        return str(self.observed.root)

    @property
    def project_root(self) -> Path:
        index = self.query_one(Select).value
        return self.threads[index].thread.worktree.path

    def compose(self) -> ComposeResult:
        with ModalPanel():
            yield SourceLabel(
                "Saved sessions · select an original identity · Esc returns to chats",
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
            yield Select(options, allow_blank=False, value=initial)
            with HistoryWindow():
                yield Contents()

    @on(Select.Changed)
    @work(exclusive=True, group="historical-selection")
    async def selected(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self._selection_generation += 1
        self.workers.cancel_group(self, "historical-handling")
        generation = self._selection_generation
        item = self.threads[event.value]
        previous = self.query_one(Contents)
        content = RecordedContents(item.source.key)
        with self.app.batch_update():
            await previous.remove()
            await self.query_one(HistoryWindow).mount(content)
        self.query_one(SourceLabel).update(
            f"@{item.thread.name} · original incarnation {item.thread.created_at}\n"
            f"Source: {item.source.original_root}\n"
            f"Channels/tags: {', '.join(sorted(item.thread.tags)) or 'none'}\n"
            f"Session: {item.thread.session_file or 'No saved session recorded'} · read only"
        )
        access, root = self.app.coordination_access, str(self.observed.root)

        async def load(**kwargs):
            snapshot = await access.transcripts.read(ReadTranscript(root, TranscriptPageRead(
                thread=item.thread.name, page_source=RecordedPageSource(item.source.key), **kwargs)))
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
            prepared = await TranscriptPageRenderTask(page).prepared(self.app.preparation)
            if generation != self._selection_generation or not self.is_attached:
                return
            history = LineHistory(prepared, SavedHistory(load, page.after, self.app.preparation),
                                  notification_view=content, source_state=LiveTranscript())
            window = self.query_one(HistoryWindow)
            window.anchor()
            await content.prepare_history(
                history, lambda: generation == self._selection_generation and self.is_attached,
                window=window,
            )
            if generation != self._selection_generation or not self.is_attached:
                return
            async with window.preserve_history():
                await content.mount(history)

    def action_focus_prompt(self) -> None:
        self.query_one(HistoryWindow).jump_to_latest()
