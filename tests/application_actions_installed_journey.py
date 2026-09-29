"""Normal installed App: physical actions, real SDK, save, close and saved reopen."""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from sidebar_retirement_pilot import until, viewport_text
from toad.application_actions import ApplicationAction, PaletteAction
from toad.preferences import UiSettings
from toad.screens.settings import SettingsScreen
from toad.setting_widgets import InputEditor
from toad.widgets.comms_sidebar import CommsSidebar, NewSessionButton
from toad.widgets.session_tabs import SessionTabClose
from textual.command import CommandPalette
from textual.widgets import Input


class DeclarationProofAction(ApplicationAction, PaletteAction):
    help = 'Declared application action needs no App dispatch or catalog edit'

    def label(self, app):
        return 'Q8 declaration proof'

    async def apply(self, app):
        (app.project_dir / 'declaration-proof.txt').write_text('Actual palette applied declaration')


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


async def palette(pilot, app, query, completed):
    await pilot.press('ctrl+p')
    await until(pilot, lambda: isinstance(app.screen, CommandPalette))
    editor = app.screen.query_one(Input)
    assert await pilot.click(editor)
    await pilot.press(*query)
    await until(pilot, lambda: app.screen._list.option_count > 0)
    await pilot.press('enter')
    await until(pilot, completed)


async def main():
    with TemporaryDirectory(prefix='application-', dir=os.environ['TMPDIR']) as directory:
        root=Path(directory)
        project=root/'project'; project.mkdir()
        config=root/'config'/'toad'; config.mkdir(parents=True)
        settings_path=config/'toad.json'
        settings_path.write_text(json.dumps({'anon_id': 'durable-original-id',
             'statistics': {'allow_collect': False}, 'ui': {'column-width': 100, 'footer': True}}))
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_CONFIG_HOME=str(root/'config'),
             XDG_STATE_HOME=str(root/'state'), XDG_DATA_HOME=str(root/'data'), TOAD_TEST_ATTEMPT=root.name)
        peer=Path(__file__).with_name('acp_completion_server.py')
        data={'name':'Q8 physical SDK peer','identity':'q8-sdk','short_name':'Q8','protocol':'acp',
              'run_command':{'*':shlex.join([sys.executable,str(peer)])}}
        app=InstalledApp(project_dir=str(project),agent_data=data)
        async with app.run_test(size=(130,44)) as pilot:
            source=app.selected_session
            view=source.conversation
            await until(pilot, lambda: view.agent is not None and view.agent.ready)
            prompt=view.prompt
            prompt.focus();await pilot.press(*'Q8_FIRST_REPLY','enter')
            await until(pilot, lambda: 'COMPLETION_PEER_EXECUTED Q8_FIRST_REPLY' in viewport_text(view.query_one('Window')))
            document=prompt.prompt_text_area.document
            prompt.focus();await pilot.press(*'retained action draft')
            draft=prompt.text
            await pilot.press('f1')
            await until(pilot,lambda:bool(app.screen.query('HelpPanel')))
            await pilot.press('f1')
            await until(pilot,lambda: not app.screen.query('HelpPanel'))
            assert prompt.text==draft and prompt.prompt_text_area.document is document
            await pilot.press('f2')
            await until(pilot,lambda:isinstance(app.screen,SettingsScreen))
            search=app.screen.query_one('#search',Input)
            await pilot.click(search);await pilot.press(*'Width of the column')
            await until(pilot,lambda: any(w.bound.kind is UiSettings.column_width for w in app.screen.query(InputEditor)))
            width=next(w for w in app.screen.query(InputEditor) if w.bound.kind is UiSettings.column_width)
            width.scroll_visible(animate=False,immediate=True);await pilot.pause()
            assert await pilot.click(width)
            await pilot.press('home','shift+end','1','2','3','escape')
            await until(pilot,lambda:app.screen is app.workspace_screen and app.settings.ui.column_width==123)
            await until(pilot,lambda:json.loads(settings_path.read_text())['ui']['column-width']==123)
            assert app.selected_session is source and source.frame_presentation.ready
            assert prompt.text==draft and prompt.prompt_text_area.document is document
            print('PHYSICAL_FIRST_REPLY_HELP_SETTINGS_BLUR_SAVE_FRAME_DRAFT_IDENTITY_PASS',flush=True)
            await palette(pilot,app,'Q8 declaration proof',lambda:(project/'declaration-proof.txt').exists())
            assert (project/'declaration-proof.txt').read_text()=='Actual palette applied declaration'
            await palette(pilot,app,'Hide footer shortcut bar',lambda:app.settings.ui.footer is False)
            assert app.has_class('-hide-footer')
            await until(pilot,lambda:json.loads(settings_path.read_text())['ui']['footer'] is False)
            print('REAL_PALETTE_NEW_DECLARATION_AND_PERSISTED_FOOTER_PAINT_PASS',flush=True)
            await pilot.press('ctrl+s')
            await until(pilot,lambda:app.screen.query_one(CommsSidebar).has_focus or app.screen.focused is not None)
            sidebar=app.screen.query_one(CommsSidebar)
            new=sidebar.query_one(NewSessionButton);new.scroll_visible(animate=False,immediate=True)
            await pilot.pause();assert await pilot.click(new)
            await until(pilot,lambda:app.selected_session is not source)
            second=app.selected_session
            await until(pilot,lambda:second.conversation.agent is not None and second.conversation.agent.ready)
            close=app.screen.query_one(f'#close-{second.id}',SessionTabClose)
            assert await pilot.click(close)
            await until(pilot,lambda:app.selected_session is source)
            assert prompt.text==draft and prompt.prompt_text_area.document is document
            print('PHYSICAL_CHANNELS_NEW_SESSION_AND_CLOSE_THROUGH_NOMINAL_REQUEST_OWNER_PASS',flush=True)
            # Actual filesystem rejection, no mocked atomic writer/protocol/UI.
            original=settings_path.read_bytes();settings_path.unlink();settings_path.mkdir()
            app.settings.ui.footer=True
            await app.settings.save()
            assert app.settings.changed and settings_path.is_dir()
            assert any(n.title=='Settings' and n.severity=='error' for n in app._notifications)
            assert not list(config.glob('.toad.json_tmp_*'))
            settings_path.rmdir();settings_path.write_bytes(original)
            await app.settings.save()
            assert json.loads(settings_path.read_text())['ui']['footer'] is True and not app.settings.changed
            print('REAL_WRITE_FAILURE_VISIBLE_DIRTY_VALUE_RETRY_AND_TEMP_RETIREMENT_PASS',flush=True)
            # Quit while editor still focused; no blur/save sleeps in product.
            await pilot.press('f2')
            await until(pilot,lambda:isinstance(app.screen,SettingsScreen))
            width=next(w for w in app.screen.query(InputEditor) if w.bound.kind is UiSettings.column_width)
            width.scroll_visible(animate=False,immediate=True);await pilot.pause()
            assert await pilot.click(width)
            await pilot.press('home','shift+end','1','3','7','ctrl+q')
            await until(pilot,lambda:app._exit)
        saved=json.loads(settings_path.read_text())
        assert saved['ui']['column-width']==137,saved
        assert saved['anon_id']=='durable-original-id'
        reopened=InstalledApp(project_dir=str(project),agent_data=data)
        async with reopened.run_test(size=(130,44)) as pilot:
            await until(pilot,lambda:reopened.selected_session.conversation.agent is not None and reopened.selected_session.conversation.agent.ready)
            assert reopened.column_width==137 and reopened.settings.ui.footer is True
            prompt=reopened.selected_session.conversation.prompt
            prompt.focus();await pilot.press(*'Q8_REOPEN_REPLY','enter')
            await until(pilot,lambda:'COMPLETION_PEER_EXECUTED Q8_REOPEN_REPLY' in viewport_text(reopened.selected_session.conversation.query_one('Window')))
            prompt.focus();await pilot.press('ctrl+c')
            assert not reopened._exit
            await pilot.press('ctrl+c')
            await until(pilot,lambda:reopened._exit)
        print('FOCUSED_EDITOR_QUIT_SAVE_DURABLE_REOPEN_FIRST_REPLY_AND_CONFIRMED_QUIT_PASS',flush=True)
        rows=list(map(json.loads,(project/'completion-wire.jsonl').read_text().splitlines()))
        assert [r['prompt'] for r in rows if 'prompt' in r]==['Q8_FIRST_REPLY','Q8_REOPEN_REPLY'],rows


if __name__=='__main__':asyncio.run(main())
