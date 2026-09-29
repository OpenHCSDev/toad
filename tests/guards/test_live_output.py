"""Root deletion and one declaration-only new live stream case."""
import ast
from pathlib import Path


def test_root_has_no_stream_store():
    path = Path(__file__).parents[2] / 'src/toad/widgets/conversation.py'
    tree = ast.parse(path.read_text())
    removed = {'_agent_response', '_agent_thought', '_post_lock', 'post_agent_response', 'post_agent_thought', 'new_block'}
    assert not [node for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr in removed
                or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in removed]


async def declaration_case():
    import os
    from tempfile import TemporaryDirectory
    from toad.live_output import OutputStream, ResponseStream, ThoughtStream
    from toad.widgets.agent_response import RoutedResponse
    from toad.widgets.agent_thought import AgentThought
    from agent_comms.routing import MessageRoute
    from toad.app import ToadApp

    class DiagnosticStream(OutputStream):
        def matches(self, incoming):
            return True

        def create(self, fragment):
            return AgentThought(fragment)

    with TemporaryDirectory(dir='.artifacts') as directory:
        root = Path(directory).resolve()
        os.environ.update(XDG_CONFIG_HOME=str(root/'config'), XDG_DATA_HOME=str(root/'data'),
                          XDG_STATE_HOME=str(root/'state'), AGENT_COMMS_ROOT=str(root/'wire'))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await app.screen.wait_content_ready()
            view = app.screen.conversation
            assert await view.output.append(ThoughtStream(), '   ') is None
            thought = await view.output.append(ThoughtStream(), 'Thinking first')
            assert await view.output.append(ThoughtStream(), ' and next') is thought
            response = await view.output.append(ResponseStream(), 'Visible answer')
            assert thought._stream is None
            assert await view.output.append(ResponseStream(), ' continued') is response
            routed = await view.output.append(ResponseStream(RoutedResponse(MessageRoute('worker', ('#test',)))), 'Routed answer')
            assert routed is not response and response._stream is None
            diagnostic = await view.output.append(DiagnosticStream(), 'New declared case')
            view.output.boundary()
            await pilot.pause(1)
            assert not view.output.streams
            assert all(block._stream is None for block in (thought, response, routed, diagnostic))
            assert thought.source == 'Thinking first and next'
            assert response.source == 'Visible answer continued'
            viewport = view.window.region
            painted = '\n'.join(strip.crop(viewport.x, viewport.right).text
                                for strip in app.screen._compositor.render_strips()[viewport.y:viewport.bottom])
            assert 'Visible answer continued' in painted and 'New declared case' in painted
            assert diagnostic.region.overlaps(viewport)
            view.output.retire()
            assert await view.output.append(DiagnosticStream(), 'Retired view must not reopen') is None
            assert app._exception is None
    print('installed nominal stream family: merge, thought completion, route split, boundary, new case, cropped paint, retirement passed')


def test_new_declared_case():
    import asyncio
    asyncio.run(declaration_case())


if __name__ == '__main__':
    test_root_has_no_stream_store()
    test_new_declared_case()
