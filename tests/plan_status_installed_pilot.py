from toad.agent_schema import AgentDefinition
"""Installed normal App receives plans from a physical official-SDK ACP peer."""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory
from typing import get_args

from textual.widget import Widget
from acp.schema import PlanEntryStatus
from runtime_fixture import ToadApp
from sidebar_retirement_pilot import reveal, until, viewport_text
from toad.plan import PlanStatus
from toad.screens.main import MainScreen
from toad.widgets.plan import Plan
from toad.widgets.strike_text import StrikeText
from toad.widgets.note import Note


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


def painted(widget, text):
    if widget not in widget.screen._compositor.visible_widgets:
        return False
    # A resized sidebar may wrap one content token over successive painted
    # rows. Read the actual cropped strips, preserving the complete token.
    painted_rows = viewport_text(widget).splitlines()
    return text in "".join(row.strip() for row in painted_rows)


async def main():
    with TemporaryDirectory(prefix="plan-wire-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        stages = [{"entries": [{"content": f"ACP_{name}_ITEM", "priority": "high", "status": name}
                               for name in get_args(PlanEntryStatus)]}]
        stages.append({"entries": [{**entry, "status": "completed"} for entry in stages[0]["entries"]]})
        stages.extend([{"entries": []}, {"entries": [stages[1]["entries"][0]]}])
        peer = Path(__file__).with_name("acp_plan_server.py")
        data = {"name": "Local ACP plan acceptance", "identity": "plan-acceptance",
                "short_name": "Plan", "protocol": "acp",
                "run_command": {"*": shlex.join([sys.executable, str(peer)])}}
        app = InstalledApp(project_dir=str(root), agent_data=AgentDefinition.decode(data))
        async with app.run_test(size=(130, 44)) as pilot:
            view = app.selected_session.conversation
            await until(pilot, lambda: view.agent is not None)
            agent = view.agent
            await until(pilot, agent.session.settled.is_set)
            assert agent.session.connected, "Real ACP startup/initialize/newSession failed"
            assert agent.process.process.returncode is None
            sidebar = await reveal(app.screen, pilot)
            sending = asyncio.create_task(agent.send_prompt(json.dumps(stages)))
            try:
                await until(pilot, lambda: bool(view.query(Plan)))
                plan = view.query_one(Plan)
                await until(pilot, lambda: len(plan.query(StrikeText)) == len(stages[0]["entries"]))
                plan.scroll_visible(animate=False, immediate=True)
                await until(pilot, lambda: painted(plan, "ACP_pending_ITEM"))
                assert not plan.all_complete
                for entry, raw in zip(plan.entries, stages[0]["entries"]):
                    assert entry.status is PlanStatus.decode(raw["status"])
                    assert entry.content.plain == raw["content"]
                    assert entry.status.marker().plain.strip() in viewport_text(plan)
                await until(pilot, lambda: painted(sidebar.query_one(Plan), "ACP_pending_ITEM"))
                assert sidebar.query_one(Plan).entries is plan.entries
                print("ACP_STDIO_ALL_STATUS_MARKERS_AND_PLAN_SIDEBAR_PAINTED", flush=True)

                (root / "plan-advance-0").touch()
                await until(pilot, lambda: plan.all_complete)
                await until(pilot, lambda: len(plan.query(StrikeText)) == len(stages[0]["entries"]) and
                            list(plan.query(StrikeText))[0].strike_time is not None)
                completed = list(plan.query(StrikeText))
                for raw, text in zip(stages[0]["entries"], completed):
                    if raw["status"] == "completed":
                        assert text.has_class("-complete") and text.strike_time is None
                    else:
                        assert text.strike_time is not None
                assert len(view.query(Plan)) == 1, "Repeated plan updates appended competing plans"
                await until(pilot, lambda: all(text.auto_refresh is None for text in completed))
                assert "ACP_pending_ITEM" in viewport_text(plan)
                assert plan.has_class("-all-complete")
                await pilot.resize_terminal(104, 35)
                plan.scroll_visible(animate=False, immediate=True)
                await until(pilot, lambda: painted(plan, "ACP_pending_ITEM"))
                print("ACP_CONTINUOUS_UPDATE_COMPLETION_ANIMATED_STABLE_COMPLETION_RESIZED_AND_PAINTED", flush=True)

                await sidebar.retire_presentation()
                assert not sidebar.panels
                (root / "plan-advance-1").touch()
                await until(pilot, lambda: not plan.entries and not plan.all_complete)
                await until(pilot, lambda: painted(plan, "No plan yet"))
                await sidebar.prepare_presentation()
                await reveal(app.screen, pilot)
                restored = sidebar.query_one(Plan)
                assert restored.entries is plan.entries
                await until(pilot, lambda: painted(restored, "No plan yet"))

                (root / "plan-advance-2").touch()
                await until(pilot, lambda: plan.all_complete and len(plan.query(StrikeText)) == 1)
                assert plan.query_one(StrikeText).has_class("-complete")
                assert plan.query_one(StrikeText).strike_time is None
                await until(pilot, lambda: painted(plan, "ACP_pending_ITEM"))
                try:
                    await until(pilot, lambda: painted(sidebar.query_one(Plan), "ACP_pending_ITEM"))
                except TimeoutError:
                    mounted = sidebar.query_one(Plan)
                    print("PLAN_REVEAL_DIAGNOSTIC", {
                        "source": [entry.content.plain for entry in sidebar.plan.entries],
                        "mounted": [entry.content.plain for entry in mounted.entries],
                        "region": str(mounted.region),
                        "visible": mounted in mounted.screen._compositor.visible_widgets,
                        "paint": viewport_text(mounted) if mounted in mounted.screen._compositor.visible_widgets else "<absent>",
                        "ancestors": [(type(owner).__name__, str(owner.region), owner.display) for owner in mounted.ancestors if isinstance(owner, Widget)],
                    }, flush=True)
                    raise
                (root / "plan-advance-3").touch()
                await asyncio.wait_for(sending, 10)
                await until(pilot, lambda: len([note for note in view.query(Note)
                            if "Invalid ACP update rejected" in note.render().plain]) == 3)
                assert plan.entries[0].content.plain == stages[0]["entries"][0]["content"]
                assert sidebar.query_one(Plan).entries is plan.entries
                assert app._exception is None
                print("ACP_EMPTY_RESET_INACTIVE_PANEL_REVEAL_AND_ALREADY_COMPLETED_REAPPEARANCE_PAINTED", flush=True)
                print("PHYSICAL_MALFORMED_STATUS_MISSING_FIELD_WRONG_TYPE_REJECTED_WITH_VISIBLE_NOTES", flush=True)
                source = app.selected_session
                original_process = agent.process.process
                editor = view.prompt.prompt_text_area
                editor.insert("Detached plan draft")
                original_document, original_history = editor.document, editor.history
                await app.session_navigation.new(lambda: MainScreen(root, agent_session_id="plan-blank"))
                assert agent.controller.surface.target is None
                detached_plan = [{"entries": [{"content": "DETACHED_PLAN_ITEM", "priority": "high", "status": "pending"}]}]
                await asyncio.wait_for(agent.send_prompt(json.dumps(detached_plan)), 10)
                await until(pilot, lambda: agent.controller.plan_entries is not None and
                            agent.controller.plan_entries[0].content.plain == "DETACHED_PLAN_ITEM")
                await app.select_session(source.id)
                view = source.conversation
                await until(pilot, lambda: bool(view.query(Plan)))
                restored_plan = view.query_one(Plan)
                restored_plan.scroll_visible(animate=False, immediate=True)
                await until(pilot, lambda: painted(restored_plan, "DETACHED_PLAN_ITEM"))
                sidebar = await reveal(source, pilot)
                await until(pilot, lambda: painted(sidebar.query_one(Plan), "DETACHED_PLAN_ITEM"))
                assert restored_plan.entries is agent.controller.plan_entries
                assert sidebar.query_one(Plan).entries is restored_plan.entries
                assert view.agent is agent and agent.process.process is original_process
                assert view.prompt.prompt_text_area.document is original_document
                assert view.prompt.prompt_text_area.history is original_history
                assert view.prompt.text == "Detached plan draft"
                assert app._exception is None
                print("DETACHED_OPERATIONAL_TYPED_PLAN_RETURN_PAINTED_SAME_AGENT_PROCESS_EDITOR", flush=True)
            finally:
                for index in range(len(stages)):
                    (root / f"plan-advance-{index}").touch()
                if not sending.done():
                    sending.cancel()
                await asyncio.gather(sending, return_exceptions=True)
                await agent.stop()
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
