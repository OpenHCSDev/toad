"""Ordinary installed native workspace, original editor state and fixed chrome."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from runtime_fixture import ToadApp
from toad.screens.workspace import WorkspaceScreen
from toad.widgets.session_tabs import SessionsTabs

async def main():
    with TemporaryDirectory(dir=os.environ['TMPDIR'], prefix='persistent-workspace-') as directory:
        root=Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_CONFIG_HOME=str(root/'config'),
                          XDG_STATE_HOME=str(root/'state'), XDG_DATA_HOME=str(root/'data'))
        app=ToadApp(project_dir=str(root))
        async with app.run_test(size=(130,44)) as pilot:
            await pilot.pause(.02)
            first=app.selected_session
            assert first is not None
            workspace=app.screen
            assert isinstance(workspace,WorkspaceScreen)
            editor=first.conversation.prompt.prompt_text_area
            editor.insert('persistent original draft')
            editor.history.checkpoint()
            editor.insert(' with undo')
            document,history=editor.document,editor.history
            header=workspace.query_one(SessionsTabs)
            second=await app.session_navigation.new(app.session_navigation.default_source)
            print("CAPTURE",type(first.presentation).__name__,id(document),id(first.presentation.state.editor.document) if first.presentation.state else None,flush=True)
            assert app.screen is workspace
            assert app.selected_session is not first
            app.selected_session.conversation.prompt.text='second draft'
            await app.select_session(first.id)
            await pilot.pause(.02)
            restored=app.selected_session.conversation.prompt.prompt_text_area
            print("RESTORE",id(restored.document),id(document),id(restored.history),id(history),type(first.presentation).__name__,flush=True)
            assert restored.document is document and restored.history is history
            restored.undo()
            assert restored.text=='persistent original draft'
            assert app.screen is workspace and workspace.query_one(SessionsTabs) is header
            await app.select_session(second.mode_name)
            assert app.selected_session.conversation.prompt.text=='second draft'
            assert app._exception is None
    print('Installed persistent native workspace/editor/chrome passed')

if __name__=='__main__':asyncio.run(main())
