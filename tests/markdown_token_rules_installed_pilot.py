"""Installed path rules render and navigate through current actual Toad sessions."""

import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path

from rich.style import Style
from textual.widgets import Markdown
from textual.widgets._markdown import MarkdownParagraph
from agent_comms.comms import Comms
from toad.app import ToadApp
from toad.screens.file_preview import FilePreviewScreen
from toad.widgets.agent_response import AgentResponse
from toad.widgets.project_panel import FilePreview


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


async def until(pilot, predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await pilot.pause(.05)


async def main():
    stage = Path(os.environ['MARKDOWN_RULES_STAGE'])
    stage.mkdir(mode=0o700, parents=True, exist_ok=False)
    project = stage / 'project'
    project.mkdir()
    target = project / 'file.py'
    target.write_text('# REAL_MARKDOWN_FILE_PREVIEW\nvalue = 42\n')
    os.environ.update(
        AGENT_COMMS_ROOT=str(stage / 'wire'),
        XDG_CONFIG_HOME=str(stage / 'config'), XDG_STATE_HOME=str(stage / 'state'),
        XDG_DATA_HOME=str(stage / 'data'),
    )
    app = InstalledApp(project_dir=str(project))
    try:
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            owner = app.selected_session
            conversation = owner.conversation
            conversation.prompt.text = 'KEEP_MARKDOWN_DRAFT'
            source = 'file.py and `file.py` but `run file.py`; [website](https://example.com).'
            response = await conversation.post(AgentResponse(source, paginate=False))
            await until(pilot, lambda: bool(response.query(MarkdownParagraph)))
            paragraph = response.query_one(MarkdownParagraph)
            assert source == response.source
            links = [span.style.meta.get('@click', '') for span in paragraph._content.spans
                     if isinstance(span.style, Style) and span.style.meta]
            assert sum(f'toad-file:{target}' in action for action in links) == 2, links
            assert any('https://example.com' in action for action in links), links
            paragraph.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            app.save_screenshot(str(stage / 'actual-path-rules.svg'))
            assert await pilot.click(paragraph, offset=(2, 0))
            await until(pilot, lambda: isinstance(app.selected_session, FilePreviewScreen))
            preview = app.selected_session.query_one(FilePreview)
            await asyncio.wait_for(preview.wait_ready(), 15)
            assert preview.path == target.resolve()
            assert preview.query_one(Markdown).source == target.read_text()
            app.save_screenshot(str(stage / 'actual-file-preview.svg'))
            await app.session_navigation.close(app.selected_session.id)
            await until(pilot, lambda: app.selected_session is owner)
            assert conversation.prompt.text == 'KEEP_MARKDOWN_DRAFT'
            assert app._exception is None
        receipt = {
            'toad': __import__('toad').__file__, 'core': __import__('agent_comms').__file__,
            'textual': __import__('textual').__file__, 'provider_calls': 0,
            'actual_installed_app': True, 'text_code_web_links_rendered': True,
            'physical_file_link_click': True, 'actual_file_preview_source': True,
            'return_preserved_draft': True, 'default_activation': False,
        }
        (stage / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    finally:
        comms = Comms(stage / 'wire')
        for thread in comms.registry.all_threads().values():
            if thread.role.executable and thread.process_alive:
                await asyncio.to_thread(comms.owners.stop, thread.name)
    print('installed actual Markdown/Textual: physical file link, exact preview, draft return PASS')


if __name__ == '__main__':
    asyncio.run(main())
