"""Textual-facing: the prompt's popups (slash commands, file search, model picker), its cursor and selection
in wrapped text, and the channel composer's mention list are Textual widgets that paint and take focus."""
from toad.session_scope import AgentAttached

import json

from agent_comms.mentions import MentionCandidate
from textual.widgets.text_area import Selection

from support.agents import peer
from support.textual_steps import painted_text, viewport_text
from toad.widgets.channel_prompt import ChannelPrompt
from toad.widgets.project_panel import ProjectSearchButton
from toad.widgets.prompt import AgentInfo
from toad.widgets.prompt_popup import PromptPopup
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import SideBarCollapsible


def completion_peer():
    return peer("completion", name="Physical completion peer", identity="completion-acceptance")


def wire_records(workspace):
    return list(map(json.loads, (workspace.project / "completion-wire.jsonl").read_text().splitlines()))


async def ready_prompt(workspace, ui):
    await ui.until_agent_ready()
    view = ui.conversation
    return view, view.prompt, view.agent


async def test_slash_command_discovered_from_the_agent_is_completed_by_keyboard_and_executed(workspace):
    async with workspace.app(size=(130, 44), binding=AgentAttached(completion_peer())) as ui:
        view, prompt, agent = await ready_prompt(workspace, ui)
        await agent.send_prompt("publish")
        await ui.until(lambda: any(command.command == "/proofcmd" for command in prompt.slash_commands),
                       why="the agent's command in the prompt")
        assert all(not popup.is_open for popup in prompt.query(PromptPopup))
        prompt.focus()
        await ui.press("/")
        slash = prompt.slash_complete
        await ui.until(lambda: slash.is_open and slash.input.has_focus, why="the slash popup")
        await ui.press(*"proof")
        await ui.until(lambda: painted_text(slash, "/proofcmd"), why="the command in the popup")
        await ui.press("enter")
        await ui.until(lambda: prompt.text == "/proofcmd " and prompt.prompt_text_area.has_focus,
                       why="the completed command in the draft")
        assert not slash.is_open
        await ui.press("enter")
        await ui.until(lambda: any("/proofcmd" in row.get("prompt", "") for row in wire_records(workspace)),
                       why="the command at the agent")
        await ui.until(lambda: painted_text(view, "COMPLETION_PEER_EXECUTED /proofcmd"), why="the agent's answer")


async def test_up_and_down_move_through_wrapped_rows_before_they_move_through_history(workspace):
    async with workspace.app(size=(130, 44), binding=AgentAttached(completion_peer())) as ui:
        view, prompt, agent = await ready_prompt(workspace, ui)
        area = prompt.prompt_text_area
        history = view.input_histories.prompt
        await history.record("PREVIOUS_DURABLE_CURSOR_INPUT")
        draft = "Wrapped reader draft " * 24
        prompt.text = draft
        prompt.focus()
        area.move_cursor((0, len(draft)))
        await ui.until(lambda: area.wrapped_document.height >= 3, why="the draft wrapped")
        end = area.cursor_location
        await ui.press("up")
        assert area.cursor_location[1] < end[1]
        assert prompt.text == draft and history.index == 0, (history.index, len(prompt.text), repr(prompt.text[:100]))
        await ui.press("down")
        assert area.cursor_location == end and prompt.text == draft and history.index == 0
        area.move_cursor((0, 0))
        await ui.press("up")
        await ui.until(lambda: prompt.text == "PREVIOUS_DURABLE_CURSOR_INPUT", why="history entry")
        await ui.press("down")
        await ui.until(lambda: prompt.text == draft, why="the draft back")
        area.move_cursor((0, 0))
        await ui.press("shift+down")
        assert prompt.text == draft and history.index == 0 and not area.selection.is_empty


async def test_a_whole_command_is_selected_backwards_and_the_agents_hint_refreshes(workspace):
    async with workspace.app(size=(130, 44), binding=AgentAttached(completion_peer())) as ui:
        view, prompt, agent = await ready_prompt(workspace, ui)
        await agent.send_prompt("publish")
        await ui.until(lambda: any(command.command == "/proofcmd" for command in prompt.slash_commands),
                       why="the agent's command in the prompt")
        area = prompt.prompt_text_area
        slash = prompt.slash_complete
        prompt.focus()
        prompt.text = "/proofcmd"
        area.move_cursor((0, len(prompt.text)))
        await ui.press("left")
        assert area.selection == Selection((0, 0), (0, len(prompt.text)))
        assert area.selected_text == "/proofcmd"
        await ui.press("x")
        assert prompt.text == "x" and not slash.is_open
        prompt.text = "/proofcmd "
        await ui.until(lambda: "ORIGINAL_ACP_HINT" in viewport_text(area), why="the agent's first hint")
        await agent.send_prompt("change-command")
        await ui.until(lambda: "UPDATED_ACP_HINT" in viewport_text(area), why="the agent's updated hint")
        assert "ORIGINAL_ACP_HINT" not in viewport_text(area)


async def test_channel_composer_completes_a_mention_with_tab_and_keeps_focus(workspace):
    async with workspace.app(size=(130, 44), binding=AgentAttached(completion_peer())) as ui:
        app, _pilot = ui.textual
        view, prompt, agent = await ready_prompt(workspace, ui)
        channel = ChannelPrompt(simple_input=True)
        await app.screen.mount(channel)
        channel.set_mention_candidates((MentionCandidate("cursor-peer", "Cursor peer"),))
        channel.focus()
        await ui.press("/", "c", "f7", "@", "c", "u")
        await ui.until(lambda: channel.mention_list.display, why="the mention list")
        assert all(not popup.is_open for popup in channel.query(PromptPopup))
        await ui.press("tab")
        await ui.until(lambda: channel.text == "@cursor-peer ", why="the completed mention")
        assert channel.prompt_text_area.has_focus


async def search_button(workspace, ui, prompt):
    sidebar = ui.app.selected_session.query_one(SessionThreadSidebar)
    sidebar.reveal()
    await sidebar.wait_content_ready()
    await ui.step()
    sidebar.query_one("#project-panel", SideBarCollapsible).collapsed = False
    await ui.until(lambda: sidebar.query_one_optional(ProjectSearchButton) is not None, why="the search button")
    button = sidebar.query_one(ProjectSearchButton)
    button.scroll_visible(animate=False, immediate=True)
    await ui.until(lambda: painted_text(button, "Search files"), why="the search button drawn")
    return button


async def test_file_search_inserts_a_path_and_follows_picker_focus_resize_and_catalog_changes(workspace):
    (workspace.project / "folder").mkdir()
    for index in range(128):
        (workspace.project / "folder" / f"target-{index:03}.txt").write_text(str(index))
    (workspace.project / "space name.txt").write_text("Space-bearing file")
    async with workspace.app(size=(130, 44), binding=AgentAttached(completion_peer())) as ui:
        _app, pilot = ui.textual
        view, prompt, agent = await ready_prompt(workspace, ui)
        prompt.text = "Attach "
        prompt.focus()
        button = await search_button(workspace, ui, prompt)
        await pilot.hover(button, offset=(3, 0))
        await pilot.click(button, offset=(3, 0))
        paths = prompt.path_search
        await ui.until(lambda: paths.is_open and paths.input.has_focus and bool(paths.display_paths),
                       why="the file picker")
        await ui.until(lambda: not paths.option_list.loading, why="the picker's list")
        await ui.press(*"space name")
        await ui.until(lambda: painted_text(paths, "space name.txt"), why="the file in the picker")
        await ui.press("enter")
        await ui.until(lambda: '"space name.txt"' in prompt.text and prompt.prompt_text_area.has_focus,
                       why="the quoted path in the draft")
        assert not paths.is_open

        await pilot.hover(button, offset=(3, 0))
        await pilot.click(button, offset=(3, 0))
        await ui.until(lambda: paths.is_open, why="the picker reopened")
        await ui.press(*"target")
        await ui.until(lambda: paths.option_list.option_count >= 20, why="candidates for the query")
        await ui.press("-", "1", "2", "7")
        await ui.until(lambda: painted_text(paths, "target-127.txt"), why="the narrowed candidate")
        await ui.press("tab")
        await ui.until(lambda: paths.show_tree_picker and paths.tree_view.has_focus, why="the tree picker")
        await ui.press("tab")
        await ui.until(lambda: not paths.show_tree_picker and paths.input.has_focus, why="focus back in the query")
        assert paths.is_open, "Moving between actual picker children closed their owner"
        await ui.resize(104, 35)
        await ui.until(lambda: painted_text(paths, "target-127.txt"), why="the candidate after resize")
        await ui.press("escape")
        await ui.until(lambda: not paths.is_open and prompt.prompt_text_area.has_focus, why="the picker dismissed")

        # Reopen after a real filesystem change; the same query must not reuse old candidates.
        (workspace.project / "folder" / "target-127.txt").unlink()
        (workspace.project / "folder" / "target-127-new.txt").write_text("Current catalog")
        prompt.project_directory_updated()
        await pilot.hover(button, offset=(3, 0))
        await pilot.click(button, offset=(3, 0))
        await ui.until(lambda: "folder/target-127-new.txt" in paths.display_paths, why="the changed catalog")
        await ui.until(lambda: not paths.option_list.loading, why="the picker's list")
        await ui.press(*"target-127")
        await ui.until(lambda: painted_text(paths, "target-127-new.txt"), why="the new file in the picker")
        assert all(option.id != "folder/target-127.txt" for option in paths.option_list.options)


async def test_model_picker_selects_through_the_agent_and_keeps_the_draft(workspace):
    async with workspace.app(size=(130, 44), binding=AgentAttached(completion_peer())) as ui:
        _app, pilot = ui.textual
        view, prompt, agent = await ready_prompt(workspace, ui)
        paths, slash = prompt.path_search, prompt.slash_complete
        prompt.text = "Unfinished draft"
        assert await pilot.click(prompt.query_one(AgentInfo))
        picker = prompt.model_switcher
        await ui.until(lambda: picker.is_open and picker.search_input.has_focus, why="the model picker")
        assert not paths.is_open and not slash.is_open
        await ui.press(*"second")
        await ui.until(lambda: painted_text(picker, "Local second"), why="the model in the picker")
        await ui.press("enter")
        await ui.until(lambda: view.agent.configuration.model.current == "local/second", why="the selected model")
        assert {"config_id": "model", "value": "local/second"} in wire_records(workspace)
        await ui.until(lambda: not picker.is_open and prompt.prompt_text_area.has_focus, why="the picker closed")
        assert prompt.text == "Unfinished draft"
        assert await pilot.click(prompt.query_one(AgentInfo))
        await ui.until(lambda: picker.search_input.has_focus, why="the picker reopened")
        await ui.press("escape")
        await ui.until(lambda: not picker.is_open and prompt.prompt_text_area.has_focus, why="the picker dismissed")
