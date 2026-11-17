"""Toolkit-neutral base for a session's project panel. Shared by Textual's
`widgets.project_panel.ProjectPanel` and Qt's `qt.project_panel.QtProjectPanel` so a
session screen can hold a project view without branching on frontend. A screen that has
no project panel holds `NO_PROJECT_VIEW`, so every caller runs the same code.
"""
from __future__ import annotations

from pathlib import Path


class ProjectView:
    """A session's project panel as its screen sees it. The base answers for a screen
    without a tree shown; frontends override where they need real behaviour."""

    def refresh_if_visible(self) -> None:
        """No tree is shown."""

    def invalidate(self) -> None:
        """No tree is shown."""

    def show_project(self, path: Path) -> None:
        """No tree follows the project."""


NO_PROJECT_VIEW = ProjectView()
