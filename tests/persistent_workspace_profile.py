"""Diagnostic only: real native attachment, four logical source-bound surfaces."""
import asyncio
import cProfile
import os
from pathlib import Path
import pstats
from native_session_retention_pilot import InstalledApp
from l0a_native_installed_pilot import main as native_fixture
from toad.screens.main import MainScreen

async def profile(app,pilot,agent,comms,*unused):
    modes=[app.selected_mode]
    for index in range(3):
        details=await app.session_navigation.new(lambda: MainScreen(agent.project_root_path,agent_session_id=f'profile-{index}'))
        modes.append(details.mode_name)
    profiler=cProfile.Profile()
    profiler.enable()
    for mode in (*reversed(modes),*modes,*reversed(modes)):
        await app.select_session(mode)
        await pilot.pause(.02)
    profiler.disable()
    with Path(os.environ['WORKSPACE_PROFILE_RECEIPT']).open('w') as output:
        pstats.Stats(profiler,stream=output).sort_stats('cumulative').print_stats(60)
    assert agent.session.connected and agent.process.process.returncode is None
    print('Actual four-tab diagnostic completed; profiler timings are not acceptance')

asyncio.run(native_fixture(app_type=InstalledApp,acceptance=profile))
