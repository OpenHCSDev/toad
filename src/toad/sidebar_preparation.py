"""Worker-prepared native bar content shared across views and bar types."""

from dataclasses import dataclass

from agent_comms import ThreadView
from textual.content import Content

from toad.session_tracker import OpenTab
from toad.widgets.activity_spinner import FRAMES, animated_label
from toad.work_preparation import ContentAddressedWork, ReusableWork, ThreadWork


@dataclass(frozen=True)
class ThreadRowInput:
    person: ThreadView
    unread: int = 0
    pinned: bool = False
    action_status: str | None = None


@dataclass(frozen=True)
class PreparedThreadRow:
    source: ThreadRowInput
    frames: tuple[Content, ...]
    tooltip: Content
    busy: bool
    signature: tuple[str, str, bool]

    def content(self, phase: int) -> Content:
        return self.frames[phase % len(self.frames)]


def prepare_thread_row(source: ThreadRowInput) -> PreparedThreadRow:
    person = source.person
    presentation = person.presentation
    summary = source.action_status if source.action_status is not None else presentation.summary
    busy = source.action_status is not None or presentation.busy
    badge = f"({source.unread}) " if source.unread else ""
    frames = tuple(Content.assemble(
        (badge, "bold $accent"),
        f"{'* ' if source.pinned else ''}"
        f"{animated_label(presentation.label, busy=presentation.busy, phase=phase)}"
        f"\n  {summary}",
    ) for phase in range(len(FRAMES) if presentation.busy else 1))
    tooltip = "\n".join(str(value) for value in (
        person.thread.name, summary, "Pinned in this channel" if source.pinned else None,
        person.runtime.model if person.runtime else person.thread.model,
    ) if value)
    return PreparedThreadRow(source, frames, Content(tooltip), busy,
                             (frames[0].plain, tooltip, busy))


@dataclass(frozen=True)
class ThreadRowsWork(ReusableWork[tuple[PreparedThreadRow, ...]],
                     ContentAddressedWork[tuple[PreparedThreadRow, ...]],
                     ThreadWork[tuple[PreparedThreadRow, ...]]):
    rows: tuple[ThreadRowInput, ...]

    @property
    def inputs(self) -> object:
        return self.rows

    def prepare(self) -> tuple[PreparedThreadRow, ...]:
        return tuple(prepare_thread_row(row) for row in self.rows)


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
        frames.append(Content.assemble(title, (f" ({tab.unread})", "bold $accent"))
                      if tab.unread else Content(title))
    return PreparedTab(tab, tuple(frames))


@dataclass(frozen=True)
class TabRosterWork(ReusableWork[tuple[PreparedTab, ...]],
                    ContentAddressedWork[tuple[PreparedTab, ...]],
                    ThreadWork[tuple[PreparedTab, ...]]):
    tabs: tuple[OpenTab, ...]

    @property
    def inputs(self) -> object:
        return self.tabs

    def prepare(self) -> tuple[PreparedTab, ...]:
        return tuple(prepare_tab(tab) for tab in self.tabs)
