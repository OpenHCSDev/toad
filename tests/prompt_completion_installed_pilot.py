"""Actual installed widgets, physical ACP, files, keyboard, pointer and resize."""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from runtime_fixture import ToadApp
from sidebar_retirement_pilot import until, viewport_text, reveal
from toad.widgets.prompt import AgentInfo
from toad.widgets.prompt_popup import PromptPopup
from toad.widgets.project_panel import ProjectSearchButton
from toad.widgets.side_bar import SideBarCollapsible


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


def painted(widget, text):
    return widget in widget.screen._compositor.visible_widgets and text in viewport_text(widget)


async def main():
    with TemporaryDirectory(prefix="completion-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        project = root / "project"
        (project / "folder").mkdir(parents=True)
        for index in range(128):
            (project / "folder" / f"target-{index:03}.txt").write_text(str(index))
        (project / "space name.txt").write_text("Space-bearing file")
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        peer = Path(__file__).with_name("acp_completion_server.py")
        data = {"name": "Physical completion peer", "identity": "completion-acceptance",
                "short_name": "Completion", "protocol": "acp",
                "run_command": {"*": shlex.join([sys.executable, str(peer)])}}
        app = InstalledApp(project_dir=str(project), agent_data=data)
        async with app.run_test(size=(130, 44)) as pilot:
            view = app.selected_session.conversation
            await until(pilot, lambda: view.agent is not None)
            agent = view.agent
            await until(pilot, agent.session_ready_event.is_set)
            assert agent._connected_ok
            try:
                await agent.send_prompt("publish")
                prompt = view.prompt
                await until(pilot, lambda: any(command.command == "/proofcmd" for command in prompt.slash_commands))
                assert all(not popup.is_open for popup in prompt.query(PromptPopup))
                prompt.focus()
                await pilot.press("/")
                slash = prompt.slash_complete
                await until(pilot, lambda: slash.is_open and slash.input.has_focus)
                await pilot.press(*"proof")
                await until(pilot, lambda: painted(slash, "/proofcmd"))
                await pilot.press("enter")
                await until(pilot, lambda: prompt.text == "/proofcmd " and prompt.prompt_text_area.has_focus)
                assert not slash.is_open
                await pilot.press("enter")
                await until(pilot, lambda: any("/proofcmd" in row.get("prompt", "") for row in
                            map(json.loads, (project / "completion-wire.jsonl").read_text().splitlines())))
                await until(pilot, lambda: painted(view, "COMPLETION_PEER_EXECUTED /proofcmd"))
                print("PHYSICAL_ACP_DISCOVERY_KEYBOARD_COMPLETION_AND_ACTUAL_SUBMISSION_PAINTED", flush=True)

                prompt.text = "Attach "
                prompt.focus()
                sidebar = await reveal(app.selected_session, pilot)
                sidebar.query_one("#project-panel", SideBarCollapsible).collapsed = False
                await until(pilot, lambda: sidebar.query_one_optional(ProjectSearchButton) is not None)
                button = sidebar.query_one(ProjectSearchButton)
                button.scroll_visible(animate=False, immediate=True)
                await until(pilot, lambda: painted(button, "Search files"))
                await pilot.hover(button, offset=(3, 0))
                await pilot.click(button, offset=(3, 0))
                paths = prompt.path_search
                await until(pilot, lambda: paths.is_open and paths.input.has_focus and bool(paths.display_paths))
                await until(pilot, lambda: not paths.option_list.loading)
                await pilot.press(*"space name")
                await until(pilot, lambda: painted(paths, "space name.txt"))
                await pilot.press("enter")
                await until(pilot, lambda: '"space name.txt"' in prompt.text and prompt.prompt_text_area.has_focus)
                assert not paths.is_open

                await pilot.hover(button, offset=(3, 0))
                await pilot.click(button, offset=(3, 0))
                await until(pilot, lambda: paths.is_open)
                await pilot.press(*"target")
                await until(pilot, lambda: paths.option_list.option_count >= 20)
                before = perf_counter()
                await pilot.press("-", "1", "2", "7")
                await until(pilot, lambda: painted(paths, "target-127.txt"))
                print(f"REAL_FILESYSTEM_128_CANDIDATE_QUERY_AND_PAINT_MS={(perf_counter()-before)*1000:.2f}", flush=True)
                await pilot.press("tab")
                await until(pilot, lambda: paths.show_tree_picker and paths.tree_view.has_focus)
                await pilot.press("tab")
                await until(pilot, lambda: not paths.show_tree_picker and paths.input.has_focus)
                assert paths.is_open, "Moving between actual picker children closed their owner"
                await pilot.resize_terminal(104, 35)
                await until(pilot, lambda: painted(paths, "target-127.txt"))
                await pilot.press("escape")
                await until(pilot, lambda: not paths.is_open and prompt.prompt_text_area.has_focus)

                # Reopen after a real filesystem change; the same query must not reuse old candidates.
                (project / "folder" / "target-127.txt").unlink()
                (project / "folder" / "target-127-new.txt").write_text("Current catalog")
                prompt.project_directory_updated()
                await pilot.hover(button, offset=(3, 0))
                await pilot.click(button, offset=(3, 0))
                await until(pilot, lambda: "folder/target-127-new.txt" in paths.display_paths)
                await until(pilot, lambda: not paths.option_list.loading)
                await pilot.press(*"target-127")
                await until(pilot, lambda: painted(paths, "target-127-new.txt"))
                assert all(option.id != "folder/target-127.txt" for option in paths.option_list.options)
                print("ACTUAL_FILES_INSERT_TREE_FOCUS_RESIZE_DISMISS_AND_CHANGED_CATALOG_PAINTED", flush=True)

                prompt.text = "Unfinished draft"
                assert await pilot.click(prompt.query_one(AgentInfo))
                picker = prompt.model_switcher
                await until(pilot, lambda: picker.is_open and picker.search_input.has_focus)
                assert not paths.is_open and not slash.is_open
                await pilot.press(*"second")
                await pilot.pause(.05)
                await until(pilot, lambda: painted(picker, "Local second"))
                await pilot.press("enter")
                await until(pilot, lambda: view.current_model.id == "local/second")
                assert {"config_id": "model", "value": "local/second"} in list(
                    map(json.loads, (project / "completion-wire.jsonl").read_text().splitlines()))
                await until(pilot, lambda: not picker.is_open and prompt.prompt_text_area.has_focus)
                assert prompt.text == "Unfinished draft"
                assert await pilot.click(prompt.query_one(AgentInfo))
                await until(pilot, lambda: picker.search_input.has_focus)
                await pilot.press("escape")
                await until(pilot, lambda: not picker.is_open and prompt.prompt_text_area.has_focus)
                assert app._exception is None
                print("PHYSICAL_ACP_MODEL_SELECTION_POINTER_FOCUS_RETURN_AND_DRAFT_PRESERVED", flush=True)
            finally:
                await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
