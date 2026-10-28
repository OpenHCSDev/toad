"""Navigation effects shared by every tab that has an existing session identity."""
from __future__ import annotations

from textual.document._editing import EditingMode
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.screens.session_view import SessionView
from toad.widget_actions import WidgetAction


class SessionViewAction(WidgetAction, affix="Action"):
    def available(self, context: SessionView) -> bool:
        return context.is_current


class ReturnToViewAction(SessionViewAction):
    """Return to the previously selected tab without closing this one."""
    title = "Previous tab"
    keys = {EditingMode: ("escape",)}
    show = True

    async def apply(self, context: SessionView) -> None:
        await context.app.session_navigation.return_from(context.app.workspace_sessions.source.identity)


class CloseViewAction(SessionViewAction):
    """Close this tab and select its surviving neighbor."""
    title = "Close tab"
    keys = {EditingMode: ("ctrl+w",)}
    priority = True

    async def apply(self, context: SessionView) -> None:
        await context.app.session_navigation.close(context.app.workspace_sessions.source.identity)
