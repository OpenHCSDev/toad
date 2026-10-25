"""Reject incomplete SDK plans rather than clearing the user's valid plan."""
from acp.schema import AgentPlanUpdate
from metaclass_registry.mro_dispatch import MroDispatch, handles


class NotificationItems(MroDispatch):
    def __init__(self, raw):
        self.raw = raw

    @handles(AgentPlanUpdate)
    def plan(self, notification: AgentPlanUpdate) -> None:
        self.require_plan_items(notification.entries, **self.raw)

    @staticmethod
    def require_plan_items(parsed, entries, **_extensions):
        # The official SDK deliberately drops invalid items. A complete plan
        # replacement may never silently turn invalid required fields into a clear.
        if len(parsed) != len(entries):
            raise ValueError('ACP plan contains invalid entries; the saved plan was not replaced')
