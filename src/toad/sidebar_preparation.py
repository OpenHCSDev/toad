"""Worker-prepared native bar content shared across views and bar types."""

from dataclasses import dataclass

from agent_comms import ThreadView
from textual.content import Content

from toad.session_tracker import OpenTab
from toad.widgets.activity_spinner import FRAMES, animated_label
from toad.work_preparation import ContentAddressedWork, SerializedWork, ThreadWork


@dataclass(frozen=True, slots=True)
class ThreadRowInput:
    person: ThreadView
    unread: int = 0
    pinned: bool = False
    action_status: str | None = None

    def presentation(self) -> "ThreadRowPresentation":
        person = self.person
        presentation = person.presentation
        return ThreadRowPresentation(
            person.thread.name, presentation.label, presentation.summary, presentation.busy,
            person.runtime.model if person.runtime else person.thread.model,
            self.unread, self.pinned, self.action_status,
        )


@dataclass(frozen=True, slots=True)
class ThreadRowPresentation:
    """Exact display inputs; poll timestamps and authority graphs are not output."""

    name: str
    label: str
    summary: str
    busy: bool
    model: str | None
    unread: int
    pinned: bool
    action_status: str | None


@dataclass(frozen=True)
class PreparedThreadRow:
    source: ThreadRowPresentation
    frames: tuple[Content, ...]
    tooltip: Content
    busy: bool
    signature: tuple[str, str, bool]

    def content(self, phase: int) -> Content:
        return self.frames[phase % len(self.frames)]


def prepare_thread_row(source: ThreadRowInput) -> PreparedThreadRow:
    return prepare_thread_presentation(source.presentation())


def prepare_thread_presentation(source: ThreadRowPresentation) -> PreparedThreadRow:
    summary = source.action_status if source.action_status is not None else source.summary
    busy = source.action_status is not None or source.busy
    badge = f"({source.unread}) " if source.unread else ""
    frames = tuple(Content.assemble(
        (badge, "bold $accent"),
        f"{'* ' if source.pinned else ''}"
        f"{animated_label(source.label, busy=source.busy, phase=phase)}"
        f"\n  {summary}",
    ) for phase in range(len(FRAMES) if source.busy else 1))
    tooltip = "\n".join(str(value) for value in (
        source.name, summary, "Pinned in this channel" if source.pinned else None, source.model,
    ) if value)
    return PreparedThreadRow(source, frames, Content(tooltip), busy,
                             (frames[0].plain, tooltip, busy))


@dataclass(frozen=True)
class ThreadRowsWork(SerializedWork[tuple[PreparedThreadRow, ...]],
                     ContentAddressedWork[tuple[PreparedThreadRow, ...]],
                     ThreadWork[tuple[PreparedThreadRow, ...]]):
    rows: tuple[ThreadRowInput, ...]

    @property
    def inputs(self) -> object:
        # ContentAddressedWork evaluates this on its worker thread. Declare the
        # semantic projection before hashing, not every field of a core record.
        return tuple(row.presentation() for row in self.rows)

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
class TabRosterWork(SerializedWork[tuple[PreparedTab, ...]],
                    ContentAddressedWork[tuple[PreparedTab, ...]],
                    ThreadWork[tuple[PreparedTab, ...]]):
    tabs: tuple[OpenTab, ...]

    @property
    def inputs(self) -> object:
        return self.tabs

    def prepare(self) -> tuple[PreparedTab, ...]:
        return tuple(prepare_tab(tab) for tab in self.tabs)
