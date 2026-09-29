"""Strict item admission where the official SDK otherwise skips invalid rows.

Imported by the SDK boundary inside its validation worker, never at UI startup.
The SDK's declarations still own the external format and field validation.
"""
from acp.schema import AgentPlanUpdate, PlanEntry
from agent_comms.mro_dispatch import MroDispatch, handles
from pydantic import TypeAdapter


class NotificationItems(MroDispatch):
    entry_schema = TypeAdapter(list[PlanEntry])

    def __init__(self, raw):
        self.raw = raw

    @handles(AgentPlanUpdate)
    def plan(self, notification: AgentPlanUpdate) -> None:
        self.require_plan_items(**self.raw)

    @classmethod
    def require_plan_items(cls, entries: object, **_extensions) -> None:
        cls.entry_schema.validate_python(entries, strict=True)
