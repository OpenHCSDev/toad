"""Physical Pi/ACP context measurement and actual visible status, loopback only."""
import asyncio
from importlib.resources import files
from pathlib import Path
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from toad import messages


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    assert not agent.context_measurement.available
    assert 'Native owner has not reported' in view.status.plain
    await view.submit_input(messages.UserInputSubmitted('CONTEXT_MEASUREMENT_NATIVE'))
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_1'))
    await until(pilot, lambda: agent.context_measurement.available)
    measurement = agent.context_measurement
    assert measurement.used > 0 and measurement.size == 32768
    frame = '\n'.join(strip.text for strip in app.screen._compositor.render_strips())
    assert measurement.percentage_display in frame, frame
    assert len(requests) == 1
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    await agent.reconnect()
    await until(pilot, agent.session_ready_event.is_set)
    await until(pilot, lambda: agent.context_measurement.available and agent.context_measurement.source_label == 'last response')
    assert len(requests) == 1, 'Saved-load measurement requested provider input'
    restored = agent.context_measurement
    assert restored.used == measurement.used and restored.size == measurement.size
    await until(pilot, lambda: 'last response' in '\n'.join(strip.text for strip in app.screen._compositor.render_strips()))
    print('ACTUAL_SAVED_USAGE_PAINTED_WITHOUT_PROVIDER', restored.used, restored.size, flush=True)
    Path('evidence/context-measurement/native.svg').write_text(app.export_screenshot())
    print('ACTUAL_NATIVE_USAGE_PAINTED', measurement.used, measurement.size,
          measurement.percentage_display, flush=True)


if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance))
