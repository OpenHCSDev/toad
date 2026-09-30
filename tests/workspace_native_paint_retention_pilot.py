"""Observe actual native paint resources through workspace A/B/A and resize."""
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from textual.widgets._markdown import MarkdownParagraph
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    evidence = Path(os.environ['PAINT_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='native-paint-', dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        Comms(root / 'wire').messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            first = app.selected_session
            view = first.conversation
            response = AgentResponse('## Retained native paint\n\n' + '\n\n'.join(
                f'Paragraph {i}: ordinary native Markdown retains terminal output.'
                for i in range(4)), paginate=False)
            await view.contents.mount(response)
            await pilot.pause(.3)
            window = view.window
            window.focus(scroll_visible=False)
            await pilot.press('end')
            await pilot.pause(.3)
            paragraphs = tuple(response.query(MarkdownParagraph))
            before = {paragraph: dict(paragraph._styles_cache._cache)
                      for paragraph in paragraphs if paragraph._styles_cache._cache}
            assert before, 'No actual native Strip output painted'
            original_children = tuple(response.walk_children())
            editor = view.prompt.prompt_text_area
            await pilot.press('w', 'a', 'r', 'm')
            second = await app.session_navigation.new(app.session_navigation.default_source)
            await app.selected_session.wait_content_ready()
            await pilot.pause(.2)
            await app.select_session(first.id)
            await pilot.pause(.3)
            same = sum(strip is paragraph._styles_cache._cache.get(row)
                       for paragraph, lines in before.items() for row, strip in lines.items())
            total = sum(len(lines) for lines in before.values())
            result = {'before_native_strips': total, 'identical_return_strips': same,
                      'same_conversation': first.conversation is view,
                      'same_native_children': tuple(response.walk_children()) == original_children,
                      'draft': editor.text, 'peer': second.mode_name}
            (evidence / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result), flush=True)
            assert result['same_conversation'] and result['same_native_children']
            assert editor.text == 'warm'
            assert same == total, result
            await response.update('## Changed native paint\n\nFresh content must replace old output.')
            await pilot.pause(.3)
            assert all(not paragraph.is_attached for paragraph in before)
            result['content_invalidates_original_paint'] = True
            changed = tuple(response.query(MarkdownParagraph))
            old = {paragraph: dict(paragraph._styles_cache._cache) for paragraph in changed}
            await pilot.resize_terminal(85, 35)
            await pilot.pause(.3)
            assert any(strip is not paragraph._styles_cache._cache.get(row)
                       for paragraph, lines in old.items() for row, strip in lines.items())
            result['resize_invalidates_paint'] = True
            assert app._exception is None
            (evidence / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(main())
