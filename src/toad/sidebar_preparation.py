"""Worker-prepared native bar content shared across views and bar types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.presentation import ThreadView
from textual.content import Content

from toad.session_tracker import OpenTab, UnreadPresentation, ExactUnread
from toad.widgets.activity_spinner import FRAMES, animated_label
from toad.work_preparation import ContentAddressedWork, RendererWork, SerializedWork

if TYPE_CHECKING:
    from toad.render_tasks import TabRosterRenderTask, ThreadRowsRenderTask
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
    unread: UnreadPresentation
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


def prepare_thread_presentation(source: ThreadRowPresentation) -> PreparedThreadRow:
    summary = source.action_status if source.action_status is not None else source.summary
    busy = source.action_status is not None or source.busy
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
    return PreparedThreadRow(source, frames, Content(tooltip), busy,
                             (frames[0].plain, tooltip, busy))


@dataclass(frozen=True)
class ThreadRowsWork(SerializedWork[tuple[PreparedThreadRow, ...]],
                     ContentAddressedWork[tuple[PreparedThreadRow, ...]],
                     RendererWork[tuple[PreparedThreadRow, ...]]):
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

    @property
    def render_task(self) -> ThreadRowsRenderTask:
        from toad.render_tasks import ThreadRowsRenderTask

        return ThreadRowsRenderTask(self.inputs)


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
                    RendererWork[tuple[PreparedTab, ...]]):
    tabs: tuple[OpenTab, ...]

    @property
    def inputs(self) -> object:
        return self.tabs

    @property
    def render_task(self) -> TabRosterRenderTask:
        from toad.render_tasks import TabRosterRenderTask

        return TabRosterRenderTask(self.tabs)
