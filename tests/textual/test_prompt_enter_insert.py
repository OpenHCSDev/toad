"""Textual-facing: vim `i` asks the prompt for insert mode; the prompt owns whether its editor exists."""

import os
import signal

import pytest
from textual import events

from agent_comms.repo import Checkout
from support.agents import RecordedEvents, peer
from toad.core.input_events import UserInputSubmitted
from toad.prompt_actions import SubmitAction, SubmitInputAction, SubmitNowAction
from toad.key_modes import Standard, VimInsert, VimNormal
from toad.preferences import SETTINGS
from toad.screens.settings import SettingsScreen
from toad.agent_origin import AgentAttached
from toad.widgets.prompt import MessagePrompt


def test_enter_insert_before_compose_has_no_editor_to_touch(tmp_path):
    MessagePrompt(project=Checkout(tmp_path)).enter_insert()


async def test_normal_profile_arrow_aliases_stay_out_of_real_insert_text(workspace):
    async with workspace.app() as ui:
        area = ui.conversation.prompt.prompt_text_area
        ui.app.saved_settings.set(SETTINGS.ui.key_mode, VimNormal)
        await ui.until(lambda: area.key_mode is VimNormal and area.editing_mode.completed,
                       why="the real child in the saved Normal profile")
        area.focus()
        await ui.press("i")
        await ui.until(lambda: area.editing_mode.accepts_text, why="real Insert entered from Normal")
        await ui.type("hjkl")
        await ui.until(lambda: area.text == "hjkl" and area.editing_mode.completed,
                       why="printable aliases to arrive as text in Insert")


async def test_escape_in_real_normal_leaves_the_box_and_keeps_vim_and_draft(workspace):
    async with workspace.app() as ui:
        area = ui.conversation.prompt.prompt_text_area
        ui.app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert and area.editing_mode.completed,
                       why="the real child in Insert")
        area.focus()
        await ui.type("draft")
        await ui.until(lambda: area.text == "draft" and area.editing_mode.completed,
                       why="a real draft to carry over")
        await ui.press("escape")
        await ui.until(lambda: area.editing_mode.allows_application_commands,
                       why="the first Escape to leave Insert for Normal, not the profile")
        assert area.key_mode is VimInsert
        await ui.press("escape")
        await ui.until(lambda: ui.conversation.window.has_focus,
                       why="Escape in Normal to leave the box for navigation")
        assert not area.has_focus
        assert ui.conversation.prompt.editing_mode_label.content == "STANDARD"
        assert area.key_mode is VimInsert and ui.app.settings.ui.key_mode is VimInsert
        assert area.text == "draft"


async def test_real_neovim_submission_shrinks_document_and_cursor_together(workspace):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        app = ui.app
        prompt = ui.conversation.prompt
        area = prompt.prompt_text_area
        app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert,
                       why="the declared Neovim insert profile")
        await ui.until(lambda: area.editing_mode.completed,
                       why="the real child to finish its initial document")
        area.focus()
        await ui.type("first")
        await ui.press("shift+enter")
        await ui.type("second")
        await ui.until(lambda: (area.text == "first\nsecond"
                                and area.cursor_location == (1, 6)
                                and area.editing_mode.completed),
                       why="the real second-line cursor before submission")
        await ui.press("enter")
        await ui.until(lambda: workspace.prompts_received() == ["first\nsecond"],
                       why="the actual private peer to receive the submitted text")
        await ui.until(lambda: (area.text == "" and area.cursor_location == (0, 0)
                                and area.editing_mode.completed),
                       why="the cleared document and cursor to publish together")
        await ui.type("still here")
        await ui.until(lambda: area.text == "still here" and area.editing_mode.completed,
                       why="the same prompt to accept input after shrinking")
        await ui.press("ctrl+c")
        await ui.until(lambda: area.text == "" and area.editing_mode.completed,
                       why="the local clear command, not the yielding app quit hint")


@pytest.mark.parametrize("rejected_action", (SubmitAction, SubmitNowAction))
async def test_refused_native_transfer_cannot_change_the_next_ordinary_submission(
    workspace, rejected_action: type[SubmitInputAction],
):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        area = ui.conversation.prompt.prompt_text_area
        ui.app.saved_settings.set(SETTINGS.ui.key_mode, VimNormal)
        await ui.until(lambda: area.key_mode is VimNormal and area.editing_mode.completed,
                       why="the real Neovim child in Normal")
        area.focus()
        await ui.press("i")
        await ui.until(lambda: area.editing_mode.accepts_text, why="real Insert")
        await ui.type("kept draft")
        await ui.press("escape")
        await ui.until(lambda: area.text == "kept draft" and area.editing_mode.allows_application_commands,
                       why="the completed draft in real Normal")
        submitted = RecordedEvents()
        subscription = area.core_publications.subscribe(UserInputSubmitted, submitted.receive)
        try:
            await ui.press("d")
            await ui.until(lambda: not area.editing_mode.completed
                           and not area.editing_mode.snapshot.state.transferable,
                           why="the actual pending Neovim operator refuses transfer")
            # Exercise the queued request's refusal, including a request whose
            # editing state became pending after its key was admitted.
            area.schedule_submission(rejected_action())
            await ui.step()
            assert area.text == "kept draft"
            assert submitted == [] and workspace.prompts_received() == []
            await ui.press("escape")
            await ui.until(lambda: area.editing_mode.allows_application_commands,
                           why="the real operator cancelled without replay")
            await ui.press("i")
            await ui.until(lambda: area.editing_mode.accepts_text, why="real Insert resumed")
            await ui.press("enter")
            await ui.until(lambda: workspace.prompts_received() == ["kept draft"],
                           why="one fresh ordinary submission reaches the real private peer")
            assert submitted == [UserInputSubmitted("kept draft")]
        finally:
            subscription.close()


@pytest.mark.parametrize("actions,immediate", (
    ((SubmitAction, SubmitAction), False),
    ((SubmitAction, SubmitNowAction, SubmitAction), True),
    ((SubmitNowAction, SubmitAction), True),
))
async def test_coalesced_prompt_actions_publish_one_owned_intent(workspace, actions, immediate):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        area = ui.conversation.prompt.prompt_text_area
        ui.app.saved_settings.set(SETTINGS.ui.key_mode, Standard)
        await ui.until(lambda: area.key_mode is Standard, why="the native Standard editor")
        area.focus()
        await ui.type("one request")
        submitted = RecordedEvents()
        subscription = area.core_publications.subscribe(UserInputSubmitted, submitted.receive)
        try:
            for action in actions:
                area.schedule_submission(action())
            await ui.until(lambda: workspace.prompts_received() == ["one request"],
                           why="the coalesced request reaches the real private peer once")
            assert submitted == [UserInputSubmitted("one request", immediate=immediate)]
        finally:
            subscription.close()


async def test_standard_chooser_retires_neovim_and_saved_selection_reopens(workspace):
    async with workspace.app() as ui:
        app = ui.app
        prompt = ui.conversation.prompt
        area = prompt.prompt_text_area
        app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert,
                       why="the declared Neovim profile")
        await ui.until(lambda: area.editing_mode.completed,
                       why="a completed real child before selecting Standard")
        engine = app.neovim
        previous = area.editing_mode
        area.focus()
        await ui.type("retained draft")
        await ui.until(lambda: area.text == "retained draft" and area.editing_mode.completed,
                       why="a real draft to transfer to the native editor")
        await ui.press("ctrl+comma")
        await ui.until(lambda: isinstance(app.screen, SettingsScreen),
                       why="the application settings binding before Neovim")
        await ui.until(lambda: str(SETTINGS.ui.key_mode) in app.screen.values,
                       why="the existing declared mode chooser")
        chooser = app.screen.values[str(SETTINGS.ui.key_mode)].editor
        assert chooser.lists(Standard)
        chooser.value = Standard
        await ui.until(lambda: app.settings.ui.key_mode is Standard and area.key_mode is Standard,
                       why="Standard selected through the real settings editor")
        await ui.until(lambda: previous._lifetime.done(), why="the Neovim session's buffer released")
        assert area.text == "retained draft"
        await ui.press("escape")
        await ui.until(lambda: app.screen is app.workspace_screen and not app.saved_settings.unsaved,
                       why="the selected profile saved after closing settings")
        area.focus()
        await ui.until(lambda: str(prompt.editing_mode_label.render()) == Standard.label,
                       why="the visible Standard label at the focused native editor")
        await ui.type(" kept")
        assert area.text == "retained draft kept"
        app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert,
                       why="returning to the declared engine profile")
        await ui.until(lambda: area.editing_mode.completed,
                       why="the new generation's real child and transferred draft")
        current = area.editing_mode
        assert current.buffer != previous.buffer, "the new generation opens its own buffer"
        assert app.neovim is engine, "one engine serves the application across generations"
        assert area.text == "retained draft kept"
        app.saved_settings.set(SETTINGS.ui.key_mode, Standard)
        await ui.until(lambda: area.key_mode is Standard,
                       why="retiring the second buffer through the same mode owner")
        await ui.until(lambda: current._lifetime.done(), why="the second buffer released")
        await app.saved_settings.save()
    async with workspace.app() as ui:
        await ui.until(lambda: ui.conversation.prompt.prompt_text_area.key_mode is Standard,
                       why="the actual saved Standard preference after reopen")
        area = ui.conversation.prompt.prompt_text_area
        assert type(area.editing_mode) is Standard
        area.focus()
        await ui.until(lambda: str(ui.conversation.prompt.editing_mode_label.render()) == Standard.label,
                       why="the saved Standard label, without starting the engine")
        await ui.type("B o stays native")
        assert "B o stays native" in area.text
        assert type(area.editing_mode) is Standard


async def test_ctrl_w_typed_into_a_channel_in_real_insert_deletes_a_word_and_keeps_the_tab(workspace):
    workspace.thread("owner", "team", running=True)
    async with workspace.app(size=(100, 36)) as ui:
        app, _pilot = ui.textual
        owner = ui.selected_tab
        await workspace.bind(app.selected_session, "owner")
        await ui.open_channel("#team", actor="owner", owner=owner)
        channel = ui.selected_tab
        area = app.selected_session.query_one("CommsChatView Prompt TextArea")
        app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert and area.editing_mode.completed,
                       why="the real child in Insert")
        area.focus()
        await ui.type("kept gone")
        await ui.until(lambda: area.text == "kept gone" and area.editing_mode.completed,
                       why="a real draft")
        await ui.press("ctrl+w")
        await ui.until(lambda: area.text == "kept " and area.editing_mode.completed,
                       why="Neovim's own ctrl+w to delete the word")
        assert ui.selected_tab == channel and area.has_focus and area.editing_mode.accepts_text


async def test_two_prompts_share_one_engine_and_each_buffer_keeps_its_own_mode(workspace):
    """Nine tabs used to start nine Neovim processes. One engine now holds a buffer per prompt,
    so leaving a buffer must cancel its pending operator and returning must restore its Insert."""
    workspace.thread("owner", "team", running=True)
    async with workspace.app(size=(100, 36)) as ui:
        app, _pilot = ui.textual
        owner = ui.selected_tab
        main = ui.conversation.prompt.prompt_text_area
        app.saved_settings.set(SETTINGS.ui.key_mode, VimNormal)
        await ui.until(lambda: main.key_mode is VimNormal and main.editing_mode.completed,
                       why="the first prompt's buffer in Normal")
        main.focus()
        await ui.press("i")
        await ui.type("first")
        await ui.until(lambda: main.text == "first" and main.editing_mode.completed
                       and main.editing_mode.accepts_text, why="the first prompt left in Insert")
        await workspace.bind(app.selected_session, "owner")
        await ui.open_channel("#team", actor="owner", owner=owner)
        channel = app.selected_session.query_one("CommsChatView Prompt TextArea")
        await ui.until(lambda: channel.key_mode is VimNormal and channel.editing_mode.completed,
                       why="the channel prompt's own buffer in Normal")
        assert channel.editing_mode._host is main.editing_mode._host, "one engine, two buffers"
        channel.focus()
        await ui.press("i")
        await ui.type("ab")
        await ui.press("escape")
        await ui.until(lambda: channel.text == "ab" and channel.editing_mode.allows_application_commands,
                       why="the channel draft in Normal")
        await ui.press("d")
        await ui.until(lambda: not channel.editing_mode.snapshot.state.transferable,
                       why="a pending operator left in the channel's buffer")
        await main.editing_mode.handle_key(main, events.Key("exclamation_mark", "!"))
        await ui.until(lambda: main.text == "first!" and main.editing_mode.completed,
                       why="the first prompt resumed in its own Insert at its own cursor")
        await ui.press("x")
        await ui.until(lambda: channel.text == "a" and channel.editing_mode.completed,
                       why="x deletes in the channel: the d it left pending was cancelled, not resumed")
        assert main.text == "first!"


async def test_a_killed_engine_restarts_and_reopens_the_prompt_from_its_text(workspace):
    """One engine serves every tab, so its death must not cost every draft: each open
    buffer reopens in a new engine from the text its prompt last painted."""
    async with workspace.app() as ui:
        area = ui.conversation.prompt.prompt_text_area
        ui.app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert and area.editing_mode.completed,
                       why="the real engine in Insert")
        area.focus()
        await ui.type("kept")
        await ui.until(lambda: area.text == "kept" and area.editing_mode.completed,
                       why="a real draft before the engine dies")
        dead = ui.app.neovim
        os.kill(dead._child.identity.pid, signal.SIGKILL)
        await ui.until(lambda: ui.app.neovim is not dead and area.editing_mode.completed,
                       why="a new engine with the prompt's buffer reopened")
        assert area.text == "kept"
        await ui.type(" again")
        await ui.until(lambda: area.text == "kept again" and area.editing_mode.completed,
                       why="the reopened buffer to take input in the new engine")


async def test_normal_hjkl_and_arrows_reach_neovim_motions(workspace):
    async with workspace.app() as ui:
        area = ui.conversation.prompt.prompt_text_area
        ui.app.saved_settings.set(SETTINGS.ui.key_mode, VimNormal)
        await ui.until(lambda: area.key_mode is VimNormal and area.editing_mode.completed,
                       why="the real child in the saved Normal profile")
        area.focus()
        await ui.press("i")
        await ui.until(lambda: area.editing_mode.accepts_text, why="real Insert entered from Normal")
        await ui.type("abc")
        await ui.press("shift+enter")
        await ui.type("def")
        await ui.press("escape")
        await ui.until(lambda: area.text == "abc\ndef" and area.cursor_location == (1, 2)
                       and area.editing_mode.allows_application_commands,
                       why="a two-line draft back in real Normal")
        for key, location in (("k", (0, 2)), ("h", (0, 1)), ("j", (1, 1)), ("l", (1, 2)),
                              ("up", (0, 2)), ("left", (0, 1)), ("down", (1, 1)), ("right", (1, 2))):
            await ui.press(key)
            await ui.until(lambda: area.cursor_location == location and area.editing_mode.completed,
                           why=f"Normal {key} to move the real Neovim cursor to {location}")
        assert area.text == "abc\ndef" and area.has_focus


async def test_escape_escape_i_in_quick_succession_reach_their_modes(workspace):
    """A person presses Escape, Escape, i without waiting for Neovim's reply to each.

    Each key must be answered in the mode the keys before it produced, not the mode
    the last completed snapshot showed when the key arrived.
    """
    async with workspace.app() as ui:
        area = ui.conversation.prompt.prompt_text_area
        ui.app.saved_settings.set(SETTINGS.ui.key_mode, VimInsert)
        await ui.until(lambda: area.key_mode is VimInsert and area.editing_mode.completed,
                       why="the real child in Insert")
        area.focus()
        await ui.type("draft")
        await ui.until(lambda: area.text == "draft" and area.editing_mode.completed,
                       why="a real draft in Insert")
        # A terminal delivers keys as they are typed; Pilot.press waits for idle between
        # keys, which hides the race. Post both the way the driver does.
        for _ in range(2):
            ui.app.post_message(events.Key("escape", None))
        await ui.until(lambda: ui.conversation.window.has_focus,
                       why="the second Escape, pressed before Neovim answered the first, "
                           "to leave the box from Normal")
        assert not area.has_focus
        await ui.press("i")
        await ui.until(lambda: area.has_focus and area.editing_mode.accepts_text,
                       why="i from navigation to focus the prompt in Insert")
        await ui.type("!")
        # Escape from Insert leaves the cursor on the last character; Vim's i inserts before it.
        await ui.until(lambda: area.text == "draf!t" and area.editing_mode.completed,
                       why="typed text to land in the returned Insert mode")
