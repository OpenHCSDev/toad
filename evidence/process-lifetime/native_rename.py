"""Actual installed native session rename, no provider request."""
import asyncio,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
from l0a_native_installed_pilot import main,until
from native_session_retention_pilot import InstalledApp

async def acceptance(app,pilot,agent,comms,entered,release,hold_next,requests):
 await until(pilot,lambda:app.selected_session.conversation.agent_ready)
 original_session=agent.session_id
 assert agent.process.accepts_session(original_session)
 agent._rename_coordination_thread('renamed-native-lifetime')
 assert comms.registry.require('renamed-native-lifetime').created_at==comms.registry.require('beta').created_at
 assert agent.coordination.thread.name=='renamed-native-lifetime'
 await agent.stop()
 assert not agent.process.accepts_session(original_session)
 agent._rename_coordination_thread('must-not-rename-after-retirement')
 assert 'must-not-rename-after-retirement' not in comms.registry.all_threads()
 assert len(requests)==0
 print('ACTUAL_NATIVE_ATTACHED_RENAME_RETIRED_REJECTION_ZERO_PROVIDER_REQUESTS',flush=True)

if __name__ == "__main__":
 asyncio.run(main(app_type=InstalledApp,acceptance=acceptance))
