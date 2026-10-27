"""Navigation effects shared by every tab that has an existing session identity."""
from textual.document._editing import EditingMode
from toad.widget_actions import WidgetAction


class SessionViewAction(WidgetAction, affix="Action"):
    def available(self, context):
        return context.id is not None


class ReturnToViewAction(SessionViewAction):
    """Return to the previously selected tab without closing this one."""
    title = "Previous tab"
    keys = {EditingMode: ("escape",)}
    show = True

    async def apply(self, context):
        await context.app.session_navigation.return_from(context.id)


class CloseViewAction(SessionViewAction):
    """Close this tab and select its surviving neighbor."""
    title = "Close tab"
    keys = {EditingMode: ("ctrl+w",)}
    priority = True

    async def apply(self, context):
        await context.app.session_navigation.close(context.id)
