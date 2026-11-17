"""Toad's native views: their geometry is declared, never written to styles."""
from __future__ import annotations

from textual.view import WidgetView

from toad.workspace_frame import WorkspaceFrame


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


class CenteredView(WidgetView):
    """A native view whose content sits in its middle.

    A view declares its geometry and ignores styles, so CenteredChildren's align never reaches it.
    Vertical alignment needs a container height, and an auto-height view has none to centre in.
    """

    height = None
    align_horizontal = "center"
    align_vertical = "middle"
