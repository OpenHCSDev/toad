"""Actual ACP attachment refusal is typed Not sent before any prompt exists."""
import asyncio
import os
from dataclasses import replace
from pathlib import Path

from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp
from saved_state_user_journey_pilot import screen_paint


async def prepare(comms, project, *_):
    owner = comms.registry.require('beta')
    # A genuine saved-owner/project mismatch is rejected by the ACP attachment
    # boundary. No transport or UI implementation is replaced.
    comms.registry.register(replace(owner, worktree=str(project / 'other-project')),
                            comms.registry.status('beta'))


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    await until(pilot, lambda: 'Not sent' in screen_paint(app))
    assert 'Unconfirmed' not in screen_paint(app)
    assert not requests and not agent.session.connected
    assert not comms.registry.require('beta').process_alive
    assert not comms.registry.require('beta').executing
    Path(os.environ['L0A_EVIDENCE'], 'startup-not-sent.txt').write_text(screen_paint(app))


if __name__ == '__main__':
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance,
                              prepare_state=prepare, attachment_expected=False,
                              provider_request_budget=0))
