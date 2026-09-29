"""Deleted root custody and inherited fencing of a declaration-only new case."""
import ast
from pathlib import Path


def test_root_custody_deleted():
    tree = ast.parse((Path(__file__).parents[2]/'src/toad/widgets/conversation.py').read_text())
    removed = {'_transcript_generation','_transcript_dirty','_needs_transcript_checkpoint',
               'displayed_transcript_cursor','_record_displayed_transcript','_compact_committed_history',
               'on_transcript_snapshot','on_transcript_changed'}
    assert not [node for node in ast.walk(tree)
                if isinstance(node,ast.Attribute) and node.attr in removed
                or isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in removed]


async def declaration_case():
    import asyncio
    import os
    from tempfile import TemporaryDirectory
    from toad.app import ToadApp
    from toad.transcript_publication import TranscriptPublication
    from toad.widgets.agent_response import AgentResponse

    class DeclaredPublication(TranscriptPublication):
        def __init__(self, owner, view, window, contents, entered, release):
            super().__init__(owner, view, window, contents)
            self.entered, self.release = entered, release

        async def publish(self):
            self.entered.set()
            await self.release.wait()
            if self.current():
                await self.contents.mount(AgentResponse('Declared publication painted'))

    with TemporaryDirectory(dir='.artifacts') as directory:
        root=Path(directory).resolve()
        os.environ.update(XDG_CONFIG_HOME=str(root/'config'),XDG_STATE_HOME=str(root/'state'),
                          XDG_DATA_HOME=str(root/'data'),AGENT_COMMS_ROOT=str(root/'wire'))
        app=ToadApp(project_dir=str(root))
        async with app.run_test(size=(120,40)) as pilot:
            await app.screen.wait_content_ready()
            view=app.screen.conversation
            entered,release=asyncio.Event(),asyncio.Event()
            pending=asyncio.create_task(view.transcript.publish(DeclaredPublication,entered,release))
            await entered.wait()
            view.transcript.invalidate()
            release.set()
            await pending
            assert not view.contents.query(AgentResponse)
            await view.transcript.publish(DeclaredPublication,entered,release)
            await pilot.pause(1)
            viewport=view.window.region
            frame='\n'.join(strip.crop(viewport.x,viewport.right).text
                            for strip in app.screen._compositor.render_strips()[viewport.y:viewport.bottom])
            assert 'Declared publication painted' in frame
            await view.contents.remove_children()
            entered.clear();release.clear()
            pending=asyncio.create_task(view.transcript.publish(DeclaredPublication,entered,release))
            await entered.wait()
            await view.transcript.close()
            release.set();await pending
            assert not view.contents.query(AgentResponse)
            assert view.transcript.view is None
            assert app._exception is None
    print('installed new publication case: inherited source/resource/generation fencing, real cropped paint, retirement passed')


def test_declared_case():
    import asyncio
    asyncio.run(declaration_case())


if __name__=='__main__':
    test_root_custody_deleted()
    test_declared_case()
