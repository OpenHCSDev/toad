"""Physical quit rejection/retry over installed App, real SDK and real filesystem."""
import asyncio
import json
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory

from application_actions_installed_journey import InstalledApp
from runtime_fixture import stop_test_children
from sidebar_retirement_pilot import until, viewport_text
from toad.preferences import UiSettings
from toad.screens.settings import SettingsScreen
from toad.setting_widgets import InputEditor
from textual.widgets import Input


def paint(app):
    return '\n'.join(strip.text for strip in app.screen._compositor.render_strips())


async def main():
    with TemporaryDirectory(prefix='quit-save-', dir=os.environ['TMPDIR']) as directory:
        root=Path(directory)
        project=root/'project';project.mkdir()
        config=root/'config'/'toad';config.mkdir(parents=True)
        path=config/'toad.json'
        path.write_text(json.dumps({'anon_id':'quit-save-durable',
            'statistics':{'allow_collect':False},'ui':{'column-width':100}}))
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'),XDG_CONFIG_HOME=str(root/'config'),
            XDG_STATE_HOME=str(root/'state'),XDG_DATA_HOME=str(root/'data'),TOAD_TEST_ATTEMPT=root.name)
        peer=Path(__file__).with_name('acp_completion_server.py')
        data={'name':'Quit save SDK peer','identity':'quit-sdk','short_name':'SDK','protocol':'acp',
              'run_command':{'*':shlex.join([sys.executable,str(peer)])}}
        app=InstalledApp(project_dir=str(project),agent_data=data)
        async with app.run_test(size=(130,44),notifications=True) as pilot:
            source=app.selected_session;view=source.conversation
            await until(pilot,lambda:view.agent is not None and view.agent.ready)
            view.prompt.focus();await pilot.press(*'QUIT_SAVE_FIRST_REPLY','enter')
            await until(pilot,lambda:'COMPLETION_PEER_EXECUTED QUIT_SAVE_FIRST_REPLY'
                        in viewport_text(view.query_one('Window')))
            view.prompt.focus();await pilot.press(*'preserved retry draft')
            draft=view.prompt.text;document=view.prompt.prompt_text_area.document
            await pilot.press('f2')
            await until(pilot,lambda:isinstance(app.screen,SettingsScreen))
            search=app.screen.query_one('#search',Input)
            assert await pilot.click(search);await pilot.press(*'Width of the column')
            await until(pilot,lambda:any(w.bound.kind is UiSettings.column_width
                                        for w in app.screen.query(InputEditor)))
            editor=next(w for w in app.screen.query(InputEditor) if w.bound.kind is UiSettings.column_width)
            editor.scroll_visible(animate=False,immediate=True);await pilot.pause()
            assert await pilot.click(editor)
            original=path.read_bytes();path.unlink();path.mkdir()
            await pilot.press('home','shift+end','1','3','7','ctrl+q')
            await until(pilot,lambda:'Failed to write' in paint(app))
            assert app.is_running and not app._exit
            assert app.settings.changed and app.settings.ui.column_width==137
            assert path.is_dir() and not list(config.glob('.toad.json_tmp_*'))
            assert view.prompt.text==draft and view.prompt.prompt_text_area.document is document
            evidence=Path(os.environ['QUIT_SAVE_EVIDENCE'])
            (evidence/'failure-painted.txt').write_text(paint(app))
            (evidence/'failure.svg').write_text(app.export_screenshot())
            print('PHYSICAL_CTRL_Q_FILESYSTEM_REJECTION_VISIBLE_ERROR_APP_OPEN_DIRTY_DRAFT_RETAINED',flush=True)
            path.rmdir();path.write_bytes(original)
            await pilot.press('ctrl+q')
            await until(pilot,lambda:app._exit)
        saved=json.loads(path.read_text())
        assert saved['ui']['column-width']==137 and saved['anon_id']=='quit-save-durable'
        assert not app.settings.changed and not list(config.glob('.toad.json_tmp_*'))
        rows=[json.loads(row) for row in (project/'completion-wire.jsonl').read_text().splitlines()]
        assert [row['prompt'] for row in rows if 'prompt' in row]==['QUIT_SAVE_FIRST_REPLY']
        print('PHYSICAL_CTRL_Q_RETRY_PERSISTS_EXACT_EDIT_AND_EXITS_NO_INPUT_REPLAY',flush=True)


async def run():
    try:
        await main()
    finally:
        await stop_test_children(os.environ.get('TOAD_TEST_ATTEMPT'))


if __name__=='__main__':asyncio.run(run())
