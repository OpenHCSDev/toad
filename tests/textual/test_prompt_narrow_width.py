"""Textual-facing: the compact prompt paints at widths too narrow for its mode label."""

import pytest
from textual.widgets.text_area import VimInsert

from support.agents import peer
from toad.session_scope import AgentAttached
from toad.widgets.prompt import Prompt


@pytest.mark.parametrize("width, label_row_below", [(0, False), (3, True)])
async def test_prompt_paints_with_fewer_columns_than_its_label(workspace, width, label_row_below):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        app, pilot = ui.textual
        editor = app.selected_session.query_one(Prompt).prompt_text_area
        editor.text = ""
        editor.placeholder = "Ask the agent something long enough to wrap"
        editor.editing_mode = VimInsert()
        editor.styles.width = width
        await pilot.pause()
        columns = editor.content_size.width
        assert columns < len(" INSERT ")
        assert editor.mode_label.cell_length == columns
        assert editor.text_width == 0
        assert editor.mode_row_below is label_row_below
        app.export_screenshot()
