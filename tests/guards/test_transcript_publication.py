"""Deleted root custody and inherited fencing of a declaration-only new case."""
import ast
from pathlib import Path


def test_publication_loaders_use_captured_actor():
    tree = ast.parse((Path(__file__).parents[2] / 'src/toad/transcript_publication.py').read_text())
    loaders = [node.args[1] for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == 'TranscriptHistory']
    assert loaders
    assert all(ast.unparse(loader) == 'self.agent.get_transcript_page' for loader in loaders)


def test_root_custody_deleted():
    tree = ast.parse((Path(__file__).parents[2]/'src/toad/widgets/conversation.py').read_text())
    removed = {'_transcript_generation','_transcript_dirty','_needs_transcript_checkpoint',
               'displayed_transcript_cursor','_record_displayed_transcript','_compact_committed_history',
               'on_transcript_snapshot','on_transcript_changed'}
    assert not [node for node in ast.walk(tree)
                if isinstance(node,ast.Attribute) and node.attr in removed
                or isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in removed]


def test_source_operation_flags_deleted():
    root = Path(__file__).parents[2] / 'src/toad'
    for relative in ('widgets/transcript_history.py', 'transcript_source_preparation.py',
                     'transcript_state.py'):
        tree = ast.parse((root / relative).read_text())
        assert not [node for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                    and node.attr in {'_loading', '_advancing'}], relative


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
            await app.screen.prepare_navigation()
            await app.screen.layout_navigation()
            view=app.selected_session.conversation
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
            # One blocked operation and a coalesced pending request share the
            # ORIGINAL source. Neither may adopt the next source at drain time.
            entered.clear();release.clear()
            view.transcript.source_requests.request(DeclaredPublication,entered,release)
            await entered.wait()
            queued_entered,queued_release=asyncio.Event(),asyncio.Event()
            queued_release.set()
            view.transcript.source_requests.request(DeclaredPublication,queued_entered,queued_release)
            view.transcript.invalidate()
            release.set()
            await view.transcript.source_requests.worker.wait()
            await pilot.pause()
            assert not view.contents.query(AgentResponse), 'A pending original request painted the replacement source'
            assert not queued_entered.is_set()
            view.transcript.source_requests.request(DeclaredPublication,queued_entered,queued_release)
            await view.transcript.source_requests.worker.wait()
            await pilot.pause()
            assert len(view.contents.query(AgentResponse)) == 1
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
    test_publication_loaders_use_captured_actor()
    test_root_custody_deleted()
    test_source_operation_flags_deleted()
    test_declared_case()
