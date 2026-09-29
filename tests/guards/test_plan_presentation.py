"""Permanent caller deletion and installed declared-case extension guard."""
import ast
import asyncio
from importlib.resources import files
from pathlib import Path

from textual.content import Content
from toad.plan import PlanItem, PlanStatus

ROOT = Path(__file__).resolve().parents[2]


def test_plan_raw_consumers_and_switches_are_deleted():
    for path in (ROOT / "src/toad").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "Entry":
                assert not isinstance(node.value, ast.Name) or node.value.id != "Plan", (path, node.lineno)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "on_acp_plan":
                assert not any(isinstance(child, ast.Constant) and child.value in
                               {"content", "priority", "status"} for child in ast.walk(node)), path
    for relative in ("src/toad/plan.py", "src/toad/widgets/plan.py"):
        source = (ROOT / relative).read_text()
        tree = ast.parse(source)
        assert "PRIORITIES" not in source and "render_status" not in source
        assert "__main__" not in source and "__registry__" not in source
        assert not any(isinstance(node, ast.Match) for node in ast.walk(tree))
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp):
                assert len(node.values) < 4, (relative, node.lineno)
            if isinstance(node, ast.Constant):
                assert node.value not in {"pending", "in_progress", "completed"}, (relative, node.lineno)
    prompt = ast.parse((ROOT / "src/toad/widgets/prompt.py").read_text())
    assert not any(isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                   and node.target.id == "plan" for node in ast.walk(prompt))


def test_new_status_owns_installed_rendering_without_consumer_edits(tmp_path, monkeypatch):
    from runtime_fixture import ToadApp
    from sidebar_retirement_pilot import until, viewport_text
    from toad.widgets.plan import Plan

    class ReviewingPlanStatus(PlanStatus):
        @classmethod
        def marker(cls):
            return Content(" R ")

    class InstalledApp(ToadApp):
        CSS_PATH = files("toad").joinpath("toad.tcss")

    for name, leaf in (("AGENT_COMMS_ROOT", "wire"), ("XDG_CONFIG_HOME", "config"),
                       ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
        monkeypatch.setenv(name, str(tmp_path / leaf))
    assert PlanStatus.decode(ReviewingPlanStatus.declared_name) is ReviewingPlanStatus

    async def run():
        app = InstalledApp(project_dir=str(tmp_path))
        async with app.run_test(size=(100, 32)) as pilot:
            plan = Plan([PlanItem(Content("DECLARED_REVIEWING_PLAN"), "medium", ReviewingPlanStatus)])
            await app.screen.conversation.post(plan)
            plan.scroll_visible(animate=False, immediate=True)
            await until(pilot, lambda: plan in app.screen._compositor.visible_widgets)
            await until(pilot, lambda: "DECLARED_REVIEWING_PLAN" in viewport_text(plan))
            assert "R" in viewport_text(plan)
            assert not plan.all_complete
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()

    asyncio.run(run())
