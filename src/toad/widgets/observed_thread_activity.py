"""An open thread's status line: a view of its row in Core's open-thread status model."""

from __future__ import annotations

from pathlib import Path

from agent_comms.coordination_errors import CoordinationReadUnavailable
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.ui_model.changes import Changes
from agent_comms.ui_model.status import ThreadStatusModel
from textual.reactive import var
from textual.widgets import Static


class ObservedThreadActivity(Static):
    """Observation never starts/settles an ACP turn or changes send admission."""

    DEFAULT_CSS = """
    ObservedThreadActivity {
        width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; color: $text-muted;
    }
    ObservedThreadActivity.-working { color: $accent; }
    ObservedThreadActivity.-unavailable { color: $warning; }
    """

    row: var[ThreadStatusModel | None] = var(None, init=False)

    def __init__(self) -> None:
        super().__init__("", markup=False)
        self.display = False
        self.thread: str | None = None

    def on_mount(self) -> None:
        self.app.coordination_access.thread_status.rows.subscribe(self.rows_changed)

    def on_unmount(self) -> None:
        self.app.coordination_access.thread_status.rows.unsubscribe(self.rows_changed)

    def bind(self, thread: str | None) -> None:
        """Show observed ``thread``'s row; None leaves the row to ``show``."""
        if thread != self.thread:
            self.thread = thread
            if thread is not None:
                self.show(self.app.coordination_access.thread_status.rows.rows.get(thread))

    def rows_changed(self, changes: Changes[str]) -> None:
        thread = self.thread
        if thread is not None and (thread in changes.changed or thread in changes.added
                                   or thread in changes.removed):
            self.show(self.app.coordination_access.thread_status.rows.rows.get(thread))

    def show(self, row: ThreadStatusModel | None) -> None:
        self.row = row

    def watch_row(self, row: ThreadStatusModel | None) -> None:
        self.display = row is not None and row.shown
        self.update("\n".join(row.lines) if row is not None else "")
        self.set_class(row is not None and row.working, "-working")
        self.set_class(row is not None and row.attention, "-unavailable")


class ThreadStatusOwner:
    """A view that shows one thread's status line (its ObservedThreadActivity).

    A thread on the observed Comms root is observed by Core's observation
    process: CoordinationAccess delivers its status row through the shared
    model and its presentation to ``thread_observed``. A thread on any other
    root is a foreign thread: the view reads it itself on each coordination
    change, as every view did before the observation service.
    """

    def status_thread(self) -> tuple[str, str] | None:
        """The (wire root, thread name) whose status this view shows, if any."""
        raise NotImplementedError

    def thread_observed(self, presentation: ThreadPresentation | None) -> None:
        """Consume the observed thread's presentation, delivered once per store change."""

    async def read_foreign_thread(self) -> ThreadPresentation | None:
        """Read a foreign thread's presentation (its root is not the observed one)."""
        raise NotImplementedError

    def foreign_thread_read(self, presentation: ThreadPresentation | None) -> None:
        """Consume a foreign thread's presentation after its own read."""

    def refresh_thread_status(self) -> None:
        access = self.app.coordination_access
        activity = self.query_one_optional(ObservedThreadActivity)
        thread = self.status_thread()
        observed = access.observed_service
        if (thread is not None and observed is not None
                and Path(thread[0]).resolve() == observed.root.resolve()):
            access.show_thread(self, thread[1])
            if activity is not None:
                activity.bind(thread[1])
            return
        access.show_thread(self, None)
        if activity is not None:
            activity.bind(None)
            if thread is None:
                activity.show(None)
        if thread is not None:
            self.run_worker(self._read_foreign_status(thread[1]), group="foreign-thread-status",
                            exclusive=True)

    async def _read_foreign_status(self, name: str) -> None:
        try:
            presentation = await self.read_foreign_thread()
            row = ThreadStatusModel.known(name, presentation)
        except CoordinationReadUnavailable:
            return  # A busy store; the next coordination change reads again.
        except (OSError, ValueError, RuntimeError):
            # Core read families present as "Agent status unavailable".
            presentation, row = None, ThreadStatusModel.unavailable(name)
        if (self.status_thread() or (None, None))[1] != name:
            return
        if (activity := self.query_one_optional(ObservedThreadActivity)) is not None:
            activity.show(row)
        self.foreign_thread_read(presentation)
