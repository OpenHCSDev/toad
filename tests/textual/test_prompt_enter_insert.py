"""Textual-facing: vim `i` asks the prompt for insert mode; the prompt owns whether its editor exists."""

from textual.widgets.text_area import VimInsert

from support.agents import peer
from toad.session_scope import AgentAttached
from toad.widgets.prompt import MessagePrompt, Prompt


def test_enter_insert_before_compose_has_no_editor_to_touch():
    MessagePrompt().enter_insert()


async def test_enter_insert_sets_insert_mode_and_focuses_the_editor(workspace):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        app, _pilot = ui.textual
        prompt = app.selected_session.query_one(Prompt)
        prompt.enter_insert()
        await ui.until(lambda: app.focused is prompt.prompt_text_area, why="the editor to take focus")
        assert isinstance(prompt.prompt_text_area.editing_mode, VimInsert)
