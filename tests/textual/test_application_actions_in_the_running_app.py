"""Textual-facing: application actions (help, settings screen, command palette, sidebar buttons, tab close) run through Textual screens and keep the session, its draft and the saved settings."""
from toad.session_scope import AgentAttached

from contextlib import asynccontextmanager
import json

from textual.command import CommandPalette
from textual.widgets import Input, OptionList

from support.applications import record_notifications
from support.agents import peer
from support.completion_record import completion_prompts
from toad.application_actions import ApplicationAction
from toad.preferences import SETTINGS
from toad.screens.settings import SettingsScreen
from toad.widgets.comms_sidebar import CommsSidebar, NewSessionButton
from toad.widgets.footer import ToadFooter
from toad.widgets.session_tabs import SessionTabClose


class DeclarationProofAction(ApplicationAction):
    """Declared application action needs no App dispatch or catalog edit."""

    async def apply(self, app):
        (app.project_dir / 'declaration-proof.txt').write_text('Actual palette applied declaration')


def save_settings(workspace, **ui):
    config = workspace.roots.attempt / "config" / "toad"
    config.mkdir(parents=True)
    path = config / "toad.json"
    path.write_text(json.dumps({'anon_id': 'durable-id', 'statistics': {'allow_collect': False},
                                'ui': {'column-width': 100, 'footer': True, **ui}}))
    return config, path


@asynccontextmanager
async def running_session(workspace, **settings):
    """The app on saved settings, its completion agent ready and one reply received."""
    config, path = save_settings(workspace, **settings)
    async with workspace.app(size=(130, 44), binding=AgentAttached(peer("completion", name="Action peer", identity="action-peer"))) as ui:
        await ui.until_agent_ready()
        await ui.type('FIRST_REPLY')
        await ui.press('enter')
        await ui.until_shows('COMPLETION_PEER_EXECUTED FIRST_REPLY')
        yield ui, ui.textual[0], config, path


async def open_column_width_editor(ui, app):
    await ui.press('ctrl+comma')
    await ui.until(lambda: isinstance(app.screen, SettingsScreen), why="the settings screen")
    assert await ui.textual[1].click(app.screen.search)
    await ui.type('Width of the column')
    await ui.until(lambda: app.screen.form.values["ui.column_width"].editor.is_mounted,
                   why="the column width editor")
    width = app.screen.form.values["ui.column_width"].editor
    width.scroll_visible(animate=False, immediate=True)
    await ui.step()
    assert await ui.textual[1].click(width)
    return width


async def palette(ui, app, query, completed):
    await ui.press('ctrl+p')
    await ui.until(lambda: isinstance(app.screen, CommandPalette), why="the command palette")
    assert await ui.textual[1].click(app.screen.query_one(Input))
    await ui.type(query)
    await ui.until(lambda: app.screen.query_one(OptionList).option_count > 0, why="palette matches")
    await ui.press('enter')
    await ui.until(completed, why=f"{query!r} to complete")


async def test_help_and_a_settings_edit_saved_on_leaving_keep_the_session_and_draft(workspace):
    async with running_session(workspace) as (ui, app, config, path):
        source = app.selected_session
        prompt = ui.conversation.prompt
        document = prompt.prompt_text_area.document
        prompt.focus()
        await ui.type('retained action draft')
        draft = ui.draft()
        await ui.press('f1')
        await ui.until(lambda: bool(app.screen.query('HelpPanel')), why="the help panel")
        await ui.press('f1')
        await ui.until(lambda: not app.screen.query('HelpPanel'), why="the help panel to close")
        assert ui.draft() == draft and prompt.prompt_text_area.document is document
        await open_column_width_editor(ui, app)
        await ui.press('home', 'shift+end', '1', '2', '3', 'escape')
        await ui.until(lambda: app.screen is app.workspace_screen and app.settings.ui.column_width == 123,
                       why="the settings screen to close with the edit applied")
        await ui.until(lambda: json.loads(path.read_text())['ui']['column-width'] == 123, why="the edit saved")
        assert app.selected_session is source and app.workspace_screen.frame_presentation.ready
        assert ui.draft() == draft and prompt.prompt_text_area.document is document


async def test_the_palette_runs_a_newly_declared_action_and_a_footer_toggle_is_saved(workspace):
    async with running_session(workspace) as (ui, app, config, path):
        await palette(ui, app, 'Declaration proof', lambda: (workspace.project / 'declaration-proof.txt').exists())
        assert (workspace.project / 'declaration-proof.txt').read_text() == 'Actual palette applied declaration'
        await palette(ui, app, 'Hide footer shortcut bar', lambda: app.settings.ui.footer is False)
        assert not app.screen.query_one(ToadFooter).display
        await ui.until(lambda: json.loads(path.read_text())['ui']['footer'] is False, why="the footer setting saved")


async def test_new_session_button_opens_creation_and_tab_close_keeps_the_original_draft(workspace):
    from toad.widgets.comms_command_dialog import CommandDialog

    async with running_session(workspace) as (ui, app, config, path):
        source = app.selected_session
        prompt = ui.conversation.prompt
        await ui.write_draft("retained action draft")
        document = prompt.prompt_text_area.document
        draft = ui.draft()
        app.workspace_chrome.channels.reveal()
        await ui.step()
        new = app.screen.query_one(CommsSidebar).query_one(NewSessionButton)
        new.scroll_visible(animate=False, immediate=True)
        await ui.until(lambda: new.region.width > 3 and new.region.height > 0,
                       why="the new-session control to be laid out")
        hit, _ = app.screen.get_widget_at(new.region.x + 3, new.region.y)
        assert hit is new, (new.region, hit, hit.region)
        assert await ui.textual[1].click(new, offset=(3, 0))
        await ui.until(lambda: isinstance(app.screen, CommandDialog),
                       why="the declared new-thread creation form")
        assert app.selected_session is source
        await ui.press("escape")
        await ui.until(lambda: app.screen is app.workspace_screen, why="creation cancelled")
        new.focus()
        await ui.press("enter")
        await ui.until(lambda: isinstance(app.screen, CommandDialog),
                       why="keyboard activation of the same creation form")
        await ui.press("escape")
        await ui.until(lambda: app.screen is app.workspace_screen, why="creation cancelled")
        assert ui.draft() == draft and prompt.prompt_text_area.document is document
        preview = workspace.project / "tab-close.txt"
        preview.write_text("A saved file to preview")
        mode = await app.session_navigation.preview(preview)
        assert await ui.textual[1].click(app.screen.query_one(f"#close-{mode}", SessionTabClose), button=2)
        await ui.until(lambda: app.selected_session is source, why="middle-click closed the preview")
        assert ui.draft() == draft and prompt.prompt_text_area.document is document


async def test_a_settings_file_that_cannot_be_written_is_reported_kept_dirty_and_saved_on_retry(workspace):
    async with running_session(workspace) as (ui, app, config, path):
        record_notifications(app)
        original = path.read_bytes()
        path.unlink()
        path.mkdir()
        app.saved_settings.set(SETTINGS.ui.footer, False)
        await app.saved_settings.save()
        assert app.saved_settings.unsaved and path.is_dir()
        await ui.until(lambda: any(n.title == 'Settings' and n.severity == 'error' for n in app._notifications),
                       why="the error notification")
        assert not list(config.glob('.toad.json_tmp_*'))
        path.rmdir()
        path.write_bytes(original)
        await app.saved_settings.save()
        assert json.loads(path.read_text())['ui']['footer'] is False and not app.saved_settings.unsaved


async def test_quitting_from_a_focused_editor_saves_it_and_the_reopened_app_replies(workspace):
    async with running_session(workspace) as (ui, app, config, path):
        await open_column_width_editor(ui, app)
        await ui.press('home', 'shift+end', '1', '3', '7', 'ctrl+q')
        await ui.until(lambda: app._exit, why="the app to exit")
    saved = json.loads(path.read_text())
    assert saved['ui']['column-width'] == 137, saved
    assert saved['anon_id'] == 'durable-id'
    async with workspace.app(size=(130, 44), binding=AgentAttached(peer("completion", name="Action peer", identity="action-peer"))) as reopened:
        await reopened.until_agent_ready()
        app = reopened.textual[0]
        assert app.settings.ui.column_width == 137 and app.settings.ui.footer is True
        await reopened.type('REOPEN_REPLY')
        await reopened.press('enter')
        await reopened.until_shows('COMPLETION_PEER_EXECUTED REOPEN_REPLY')
        await reopened.press('ctrl+c')
        assert not app._exit
        await reopened.press('ctrl+c')
        await reopened.until(lambda: app._exit, why="the confirmed quit")
    assert completion_prompts(workspace) == ['FIRST_REPLY', 'REOPEN_REPLY']


async def test_column_alignment_moves_the_whole_conversation_and_is_saved(workspace):
    async with running_session(workspace, column=True, **{"column-width": 60}) as (ui, app, config, path):
        conversation = ui.conversation

        def positioned(fraction):
            available = conversation.parent.content_region
            return (conversation.region.width == 60
                    and conversation.region.x == available.x + int((available.width - 60) * fraction))

        await ui.until(lambda: positioned(0), why="default left-aligned column")
        for name, keys, fraction in (("center", ("home", "down"), .5),
                                     ("right", ("end",), 1),
                                     ("left", ("home",), 0)):
            await ui.press('ctrl+comma')
            await ui.until(lambda: isinstance(app.screen, SettingsScreen), why="settings")
            assert await ui.textual[1].click(app.screen.search)
            await ui.type('Column alignment')
            await ui.until(lambda: app.screen.form.values["ui.column_alignment"].editor.is_mounted,
                           why="alignment selector")
            selector = app.screen.form.values["ui.column_alignment"].editor
            selector.scroll_visible(animate=False, immediate=True)
            await ui.step()
            selector.focus()
            await ui.press('enter', *keys, 'enter', 'escape')
            await ui.until(lambda: app.screen is app.workspace_screen, why="return to conversation")
            await ui.until(lambda: positioned(fraction), why=f"{name}-aligned actual column")
            assert app.settings.ui.column_alignment.declared_name == name
            await ui.until(lambda: json.loads(path.read_text())['ui']['column-alignment'] == name,
                           why="alignment saved")
            assert ui.conversation is conversation
        await ui.type('ALIGNED_REPLY')
        await ui.press('enter')
        await ui.until_shows('COMPLETION_PEER_EXECUTED ALIGNED_REPLY')
