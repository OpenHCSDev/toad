"""Toad's native views: their geometry is declared, never written to styles."""
from __future__ import annotations

from typing import TYPE_CHECKING

from textual.view import WidgetView

if TYPE_CHECKING:
    from toad.screens.workspace import WorkspaceFrame



class WorkspaceHosted:
    """A widget whose native screen supplies the workspace frame and histories."""

    @property
    def screen(self) -> WorkspaceFrame:
        from toad.screens.workspace import WorkspaceFrame

        return WorkspaceFrame.require(super().screen)


class CenteredView(WidgetView):
    """A native view whose content sits in its middle.

    A view declares its geometry and ignores styles, so CenteredChildren's align never reaches it.
    Vertical alignment needs a container height, and an auto-height view has none to centre in.
    """

    height = None
    align_horizontal = "center"
    align_vertical = "middle"
