"""Textual-facing: a newly declared plan status is drawn by the Plan widget with no consumer edits."""

from toad.plan import PlanItem, PlanStatus
from toad.widgets.plan import Plan


class ReviewingPlanStatus(PlanStatus):
    @classmethod
    def marker(cls):
        return " R "


def test_a_declared_status_is_found_by_its_name():
    assert PlanStatus.member_named(ReviewingPlanStatus.declared_name) is ReviewingPlanStatus


async def test_a_declared_status_is_painted_in_the_plan(workspace):
    async with workspace.app(size=(100, 32)) as ui:
        plan = Plan([PlanItem("DECLARED_REVIEWING_PLAN", "medium", ReviewingPlanStatus)])
        await ui.conversation.post(plan)
        plan.scroll_visible(animate=False, immediate=True)
        await ui.until(lambda: "DECLARED_REVIEWING_PLAN" in ui.painted(plan), why="the plan item painted")
        assert "R" in ui.painted(plan)
        assert not plan.all_complete
