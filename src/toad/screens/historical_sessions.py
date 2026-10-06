"""Saved sessions, including older/ambiguous identities, inside normal Comms."""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from typing import ClassVar

from agent_comms.comms import Comms
from agent_comms.coordination_errors import StaleRevision
from agent_comms.mro_dispatch import handles
from toad.core.source_events import MessageHandlingRequested
from toad.core_event_carrier import CoreEventMessage, CoreEventReceiver
from agent_comms import HistoricalMessage, HistoricalThread
from agent_comms.presentation import MessageNotification
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalGroup
from textual.screen import ModalScreen
from textual.widgets import Select, Static

from toad.screens.workspace import WorkspaceScreen
from toad.project_path_owner import ProjectPathOwner
from toad.widgets.history_anchor import HistoryWindow
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.wire_message_handling import WireMessageHandling


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
            with HistoryWindow(id="saved-window"):
                yield VerticalGroup(id="saved-content")

    @on(Select.Changed, "#saved-identity")
    async def selected(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self._selection_generation += 1
        self.workers.cancel_group(self, "historical-handling")
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
            self.comms.transcripts.capture_page_read,
            item.thread.name,
            historical_source=item.source.key,
        )

        async def load(**kwargs):
            def read():
                return loader(**kwargs).read()

            return await asyncio.to_thread(read)

        try:
            page = await load()
        except (OSError, ValueError, StaleRevision) as error:
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
            history = TranscriptHistory(page, load)
            await history.prepare_body(lambda: generation == self._selection_generation and self.is_attached)
            if generation != self._selection_generation or not self.is_attached:
                return
            await content.mount(history)
            self.query_one(HistoryWindow).scroll_end(animate=False, immediate=True)

    def action_focus_prompt(self) -> None:
        self.query_one(HistoryWindow).jump_to_latest()

    @handles(MessageHandlingRequested)
    def request_message_handling(self, message: CoreEventMessage) -> None:
        message.stop()
        index = self.query_one("#saved-identity", Select).value
        self.run_worker(partial(self.publish_handling, self.threads[index],
                                self._selection_generation),
                        group="historical-handling", exclusive=True)

    async def publish_handling(self, item: HistoricalThread, generation: int) -> None:
        """Read the selected archive, never today's-name live notification."""
        if generation != self._selection_generation or not self.is_attached:
            return
        content = self.query_one("#saved-content", VerticalGroup)
        bodies = WireMessageHandling.within(content)
        references = WireMessageHandling.references_in(bodies)
        if not references:
            return

        def read():
            item.source.validate()
            # Source-only Comms reads admit no protocol initialization, claim
            # or historical execution; the original frozen registry owns joins.
            original = Comms(Path(item.source.root), private_initial_writes=False,
                             private_claim_writes=False)
            order = self.comms.bus.history.sources().index(item.source)
            messages = tuple(HistoricalMessage.project(message, item.source, order,
                                                       item.source.provenance)
                             for message in original.bus.log.messages_for_references(references))
            results = {}
            for start in range(0, len(messages), MessageNotification.window_limit):
                results.update(original.views.message_notifications(
                    messages[start:start + MessageNotification.window_limit]))
            item.source.validate()
            return results

        try:
            results = await asyncio.to_thread(read)
        except (OSError, ValueError) as error:
            if generation == self._selection_generation and self.is_attached:
                for body in bodies:
                    if body.is_attached:
                        body.show_notification_error(error)
            return
        if generation == self._selection_generation and self.is_attached:
            for body in bodies:
                if body.is_attached:
                    body.show_notifications(results)

    def action_close(self) -> None:
        self.dismiss()
