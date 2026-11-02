"""Views hosted by Toad's native workspace screen."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.screens.workspace import WorkspaceFrame



class WorkspaceHosted:
    """A widget whose native screen supplies the workspace frame and histories."""

    @property
    def screen(self) -> WorkspaceFrame:
        from toad.screens.workspace import WorkspaceFrame

        return WorkspaceFrame.require(super().screen)
