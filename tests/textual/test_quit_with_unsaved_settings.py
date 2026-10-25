"""Textual-facing: quitting with a settings edit that cannot be written keeps the app open, shows the error and keeps the draft; a retry saves the exact edit and exits."""
from toad.session_scope import AgentAttached

import json

from support.applications import record_notifications
from support.agents import peer
from support.completion_record import completion_prompts
from toad.screens.settings import SettingsScreen


async def test_quit_that_cannot_save_stays_open_and_a_retry_saves_the_edit_and_exits(workspace):
    config = workspace.roots.attempt / 'config' / 'toad'
    config.mkdir(parents=True)
    path = config / 'toad.json'
    path.write_text(json.dumps({'anon_id': 'quit-save-durable', 'statistics': {'allow_collect': False},
                                'ui': {'column-width': 100}}))
    async with workspace.app(size=(130, 44), binding=AgentAttached(peer("completion", name="Quit save peer", identity="quit-save-peer"))) as ui:
        app, pilot = ui.textual
        view = ui.conversation
        record_notifications(app)
        await ui.until_agent_ready()
        await ui.type('QUIT_SAVE_FIRST_REPLY')
        await ui.press('enter')
        await ui.until_shows('COMPLETION_PEER_EXECUTED QUIT_SAVE_FIRST_REPLY')
        view.prompt.focus()
        await ui.type('preserved retry draft')
        draft = ui.draft()
        document = view.prompt.prompt_text_area.document
        await ui.press('ctrl+comma')
        await ui.until(lambda: isinstance(app.screen, SettingsScreen), why="the settings screen")
        assert await pilot.click(app.screen.search)
        await ui.type('Width of the column')
        await ui.until(lambda: app.screen.form.values["ui.column_width"].editor.is_mounted,
                       why="the column width editor")
        editor = app.screen.form.values["ui.column_width"].editor
        editor.scroll_visible(animate=False, immediate=True)
        await ui.step()
        assert await pilot.click(editor)
        original = path.read_bytes()
        path.unlink()
        path.mkdir()
        await ui.press('home', 'shift+end', '1', '3', '7', 'ctrl+q')
        await ui.until_shows('Failed to write')
        assert app.is_running and not app._exit
        assert app.saved_settings.unsaved and app.settings.ui.column_width == 137
        assert path.is_dir() and not list(config.glob('.toad.json_tmp_*'))
        assert view.prompt.text == draft and view.prompt.prompt_text_area.document is document
        path.rmdir()
        path.write_bytes(original)
        await ui.press('ctrl+q')
        await ui.until(lambda: app._exit, why="the app to exit after the retry")
    saved = json.loads(path.read_text())
    assert saved['ui']['column-width'] == 137 and saved['anon_id'] == 'quit-save-durable'
    assert not app.saved_settings.unsaved and not list(config.glob('.toad.json_tmp_*'))
    assert completion_prompts(workspace) == ['QUIT_SAVE_FIRST_REPLY']
