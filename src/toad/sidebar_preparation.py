"""Worker-prepared native bar content shared across views and bar types."""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping
from typing import TYPE_CHECKING

from agent_comms.presentation import ThreadView
from agent_comms.thread_identity import ThreadIncarnation
from textual.content import Content

from toad.session_tracker import OpenTab, UnreadPresentation, ExactUnread
from toad.widgets.activity_spinner import FRAMES, animated_label
from toad.work_preparation import ContentAddressedWork, SerializedWork, ThreadWork

if TYPE_CHECKING:
    from toad.work_preparation import PreparationRuntime


@dataclass(frozen=True, slots=True)
class ThreadRowInput:
    person: ThreadView
    unread: UnreadPresentation = ExactUnread()
    pinned: bool = False
    action_status: str | None = None

    def presentation(self) -> "ThreadRowPresentation":
        person = self.person
        presentation = person.presentation
        return ThreadRowPresentation(
            person.thread.incarnation, presentation.title, presentation.label,
            presentation.summary, presentation.busy,
            person.runtime.model if person.runtime else person.thread.model,
            self.unread, self.pinned, self.action_status,
        )


@dataclass(frozen=True, slots=True)
class ThreadRowPresentation:
    """Exact display inputs; poll timestamps and authority graphs are not output."""

    incarnation: ThreadIncarnation
    title: str
    label: str
    summary: str
    busy: bool
    model: str | None
    unread: UnreadPresentation
    pinned: bool
    action_status: str | None

    @property
    def name(self) -> str:
        return self.incarnation.name


@dataclass(frozen=True)
class PreparedThreadRow:
    source: ThreadRowPresentation
    frames: tuple[Content, ...]
    tooltip: Content

    @property
    def busy(self) -> bool:
        return self.source.action_status is not None or self.source.busy

    def content(self, phase: int) -> Content:
        return self.frames[phase % len(self.frames)]


def prepare_thread_presentation(source: ThreadRowPresentation) -> PreparedThreadRow:
    summary = source.action_status if source.action_status is not None else source.summary
    badge = f"{source.unread.label} " if source.unread.label else ""
    frames = tuple(Content.assemble(
        (badge, "bold $accent"),
        f"{'* ' if source.pinned else ''}"
        f"{animated_label(source.label, busy=source.busy, phase=phase)}"
        f"\n  {summary}",
    ) for phase in range(len(FRAMES) if source.busy else 1))
    tooltip = "\n".join(str(value) for value in (
        source.name, summary, source.unread.detail, "Pinned in this channel" if source.pinned else None, source.model,
    ) if value)
    return PreparedThreadRow(source, frames, Content(tooltip))


@dataclass(frozen=True)
class ThreadRowsWork(SerializedWork[tuple[PreparedThreadRow, ...]],
                     ContentAddressedWork[tuple[PreparedThreadRow, ...]],
                     ThreadWork[tuple[PreparedThreadRow, ...]]):
    """Prepare captured sidebar labels independently of transcript rendering."""

    rows: tuple[ThreadRowPresentation, ...]

    @classmethod
    async def capture(cls, runtime: PreparationRuntime, rows: tuple[ThreadRowInput, ...]) -> ThreadRowsWork:
        """Resolve the original display inputs once before reuse or rendering.

        ThreadView.presentation may inspect its original process identity. Keep
        that source read off the native pump, and hash/render the same captured
        inputs rather than making another decision after an asynchronous wait.
        """
        if not rows:
            return cls(())
        return cls(await runtime.run_thread(lambda: tuple(row.presentation() for row in rows)))

    @property
    def inputs(self) -> tuple[ThreadRowPresentation, ...]:
        return self.rows

    def for_thread(self, name: str) -> ThreadRowPresentation | None:
        """Borrow this publication's original captured answer, without rereading a process."""
        return next((row for row in self.rows if row.name == name), None)

    def for_rows[Key](self, rows: Mapping[Key, ThreadRowInput]) -> dict[Key, ThreadRowPresentation]:
        """Project row-local decoration from this publication's captured people."""
        people = {row.name: row for row in self.rows}
        return {key: replace(people[row.person.thread.name], unread=row.unread,
                             pinned=row.pinned, action_status=row.action_status)
                for key, row in rows.items()}

    @property
    def content_width(self) -> int:
        """Measure the same captured display text used by row preparation."""
        return max((Content(text).cell_length for row in self.rows
                    for text in (row.label, row.summary)), default=0)

    def prepare(self) -> tuple[PreparedThreadRow, ...]:
        return tuple(prepare_thread_presentation(row) for row in self.rows)


@dataclass(frozen=True)
class PreparedTab:
    source: OpenTab
    frames: tuple[Content, ...]

    def content(self, phase: int) -> Content:
        return self.frames[phase % len(self.frames)]


def prepare_tab(tab: OpenTab) -> PreparedTab:
    busy = tab.title.startswith(("⌛ ", "● "))
    frames = []
    for phase in range(len(FRAMES) if busy else 1):
        title = animated_label(tab.title, busy=busy, phase=phase)
        frames.append(Content.assemble(title, (f" {tab.unread.label}", "bold $accent"))
                      if tab.unread.label else Content(title))
    return PreparedTab(tab, tuple(frames))


@dataclass(frozen=True)
class TabRosterWork(SerializedWork[tuple[PreparedTab, ...]],
                    ContentAddressedWork[tuple[PreparedTab, ...]],
                    ThreadWork[tuple[PreparedTab, ...]]):
    """Prepare short tab labels independently of transcript renderer admission."""

    tabs: tuple[OpenTab, ...]

    @property
    def inputs(self) -> object:
        return self.tabs

    def prepare(self) -> tuple[PreparedTab, ...]:
        return tuple(prepare_tab(tab) for tab in self.tabs)
