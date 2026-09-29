"""Real saved reply -> physical model/thinking picker -> ACP config -> retained paint."""
import asyncio
import os
from pathlib import Path
from importlib.resources import files
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from toad import messages
from toad.widgets.prompt import AgentInfo
from toad.widgets.comms_menu import ContextMenu

class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')

async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    await view.submit_input(messages.UserInputSubmitted('CONFIGURATION_SAVED_HISTORY'))
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_1'), 30)
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    view.prompt.text = 'CONFIGURATION_UNSENT_DRAFT'
    document = view.prompt.prompt_text_area.document
    undo = view.prompt.prompt_text_area.history
    assert await pilot.click(view.prompt.query_one(AgentInfo))
    picker = view.prompt.model_switcher
    await until(pilot, lambda: picker.search_input.has_focus)
    await pilot.press('down', 'enter')
    await until(pilot, lambda: isinstance(app.screen, ContextMenu))
    high = next(item for item in app.screen.query('ContextMenuItem') if item.action == 'high')
    await until(pilot, lambda: high in app.screen._compositor.visible_widgets and high.region.width > 0)
    assert await pilot.click(high, offset=(1, 0))
    await until(pilot, lambda: view.thinking_level == 'high')
    assert comms.registry.require('beta').thinking_level == 'high'
    assert agent.configuration.thinking.current == 'high'
    await agent.session.reconnect()
    await until(pilot, agent.session.settled.is_set)
    await until(pilot, lambda: view.thinking_level == 'high' and view.agent_ready)
    assert view.prompt.text == 'CONFIGURATION_UNSENT_DRAFT'
    assert view.prompt.prompt_text_area.document is document
    assert view.prompt.prompt_text_area.history is undo
    assert len(requests) == 1
    frame = '\n'.join(strip.text for strip in app.screen._compositor.render_strips())
    assert 'high' in frame and 'NATIVE_RESPONSE_1' in frame and 'CONFIGURATION_UNSENT_DRAFT' in frame, frame
    root = Path(os.environ['L0A_EVIDENCE'])
    (root / 'configuration.svg').write_text(app.export_screenshot())
    print('ACTUAL_NATIVE_PHYSICAL_CONFIG_SAVED_HISTORY_REOPEN_DRAFT_PAINT_ONCE', flush=True)

if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance))
