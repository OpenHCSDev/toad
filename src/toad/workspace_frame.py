"""The toolkit-neutral workspace-frame contract.

`WorkspaceHosted` widgets need a few things from their screen that neither Textual's
`Screen` nor Qt's `QWidget.window()` provides on its own: the set of attached history
windows, a deferral mechanism bound to the frame cycle, sidebar navigation and focus
hooks, lifecycle flags and the coordination root. Each backend's concrete frame
(Textual: `toad.screens.workspace.WorkspaceFrame`; Qt: `toad.qt.workspace_frame.QtWorkspaceFrame`)
satisfies this protocol, so a widget declaring `WorkspaceHosted` reaches its frame
through one typed surface regardless of toolkit.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from toad.frame_presentation import FramePresentation
    from toad.history_jump import JumpsToLatest


@runtime_checkable
class WorkspaceFrame(Protocol):
    """What a `WorkspaceHosted` widget asks of its screen.

    Both backends' concrete frame classes satisfy this; consumers typed against the
    protocol use neither Textual's Screen nor Qt's QWidget directly.
    """

    @property
    def history_windows(self) -> set[JumpsToLatest]:
        """Mounted history windows registered with this frame; each adds and removes
        itself for its lifetime."""

    @property
    def frame_presentation(self) -> FramePresentation:
        """The frame's own presentation cycle; `.defer(owner, callback)` schedules work
        onto the next published frame."""

    @property
    def is_current(self) -> bool:
        """Whether this frame is the active one the reader is looking at."""

    @property
    def is_active(self) -> bool:
        """Whether this frame is currently receiving input and events."""

    def start_sidebar_navigation(self, sidebar) -> None:
        """Deferred-start the sidebar's own navigation at the next published frame."""

    def focus_sidebar_return(self) -> None:
        """Return focus to the widget the user was on when the sidebar opened."""

    def belongs_to_wire(self, root: Path) -> bool:
        """Whether this frame follows the given project root."""

    def reader_kept(self, window: JumpsToLatest) -> None:
        """Signal that a history window's reader is kept at its current row."""


class WorkspaceHosted:
    """A widget whose native screen satisfies the shared workspace-frame contract."""

    @property
    def screen(self) -> WorkspaceFrame:
        """The containing workspace frame as the toolkit-neutral contract. Textual
        widgets inherit this alongside `Widget`, so `super().screen` yields the Textual
        `Screen`; the concrete Textual `WorkspaceFrame` structurally satisfies the
        protocol. Qt widgets override this to return their own `QtWorkspaceFrame`."""
        got = super().screen
        if not isinstance(got, WorkspaceFrame):
            raise TypeError(f"{type(got).__name__} does not satisfy WorkspaceFrame")
        return got
