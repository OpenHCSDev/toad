"""The public native callback keeps its synchronous or asynchronous calling contract."""
from textual.widgets import Static
from toad.widget_actions import DeclaredWidgetActions, WidgetAction


class CallbackAction(WidgetAction, affix="Action"):
    def available(self, context):
        return context.enabled


class SynchronousCallbackAction(CallbackAction):
    def apply(self, context):
        context.effects.append("sync")


class AsynchronousCallbackAction(CallbackAction):
    async def apply(self, context):
        context.effects.append("async")


class CallbackControl(DeclaredWidgetActions, Static, actions=(CallbackAction,)):
    def __init__(self):
        super().__init__()
        self.enabled = True
        self.effects = []


async def test_generated_native_callbacks_preserve_calling_and_disabled_behavior():
    control = CallbackControl()
    assert control.action_synchronous_callback() is None
    assert control.effects == ["sync"]
    pending = control.action_asynchronous_callback()
    assert control.effects == ["sync"]
    await pending
    assert control.effects == ["sync", "async"]
    control.enabled = False
    assert control.action_synchronous_callback() is None
    await control.action_asynchronous_callback()
    assert control.effects == ["sync", "async"]
