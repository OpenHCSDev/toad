"""A genuine pre-native OS failure has one typed UI outcome and retains the draft."""
import asyncio
import os
from pathlib import Path

from agent_comms.input_disposition import InputDispositions
from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp
from saved_state_user_journey_pilot import submit_editor, screen_paint
from toad.widgets.note import Note


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    project = agent.project_root_path
    project.chmod(0)  # Real child cwd refusal in this disposable fixture.
    try:
        await submit_editor(pilot, view.prompt.prompt_text_area, 'UNSENT_OS_FAILURE_FIXTURE')
        await until(pilot, lambda: agent.presentation.prompt_in_flight == 0 and not comms.registry.require('beta').executing)
        await until(pilot, lambda: 'Not sent' in screen_paint(app))
        await until(pilot, lambda: 'UNSENT_OS_FAILURE_FIXTURE' in view.prompt.text)
        paint = screen_paint(app)
        errors = [note for note in view.query(Note) if note.has_class('-error')]
        assert len(errors) == 1, [str(note.render()) for note in errors]
        assert 'Internal error' not in paint and 'Unconfirmed' not in paint
        assert not requests
        rows = InputDispositions(comms.root / InputDispositions.filename).read().rows.values()
        assert any(row.source_text == 'UNSENT_OS_FAILURE_FIXTURE' and row.public_status == 'not_sent' for row in rows)
        Path(os.environ['L0A_EVIDENCE'], 'single-failure.txt').write_text(paint)
    finally:
        project.chmod(0o700)
    # Clear the recovered fixture draft only after retaining it in the evidence.
    view.prompt.text = ''
    await submit_editor(pilot, view.prompt.prompt_text_area, 'DISTINCT_INPUT_AFTER_OS_REPAIR')
    await until(pilot, entered.is_set)
    release.set()
    await until(pilot, lambda: 'NATIVE_RESPONSE_1' in screen_paint(app))
    assert len(requests) == 1 and 'UNSENT_OS_FAILURE_FIXTURE' not in str(requests[0]['messages'])


if __name__ == '__main__':
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance))
