import asyncio, json, os, tempfile, traceback
from pathlib import Path
from agent_comms import Thread,wire
from toad.app import ToadApp
from toad.screens.historical_sessions import HistoricalSessions
from toad.widgets.transcript_history import TranscriptHistory
from textual.widgets import Select

async def until(predicate):
 async with asyncio.timeout(8):
  while not predicate():await asyncio.sleep(.02)

async def main():
 original=wire();historical=original.historical_threads()
 with tempfile.TemporaryDirectory(dir='.test-artifacts') as d:
  root=Path(d).resolve();os.environ.update(AGENT_COMMS_ROOT=str(root/'live'),XDG_CONFIG_HOME=str(root/'config'),XDG_STATE_HOME=str(root/'state'),XDG_DATA_HOME=str(root/'data'))
  app=ToadApp(project_dir=str(root))
  async with app.run_test(size=(120,40)) as pilot:
   await pilot.pause();modal=HistoricalSessions(original,historical);app.push_screen(modal)
   await until(lambda:bool(modal.query(Select)))
   print('select mounted',flush=True)
   index=next(i for i,item in enumerate(historical) if item.thread.name=='agent-comms-ux' and item.thread.session_file)
   modal.query_one(Select).value=index
   try:
    await until(lambda:bool(modal.query(TranscriptHistory)))
    print('second mounted',flush=True)
   except TimeoutError:
    for t in asyncio.all_tasks():
     print('\nTASK',t,flush=True);t.print_stack()
    raise
if __name__ == '__main__':
    asyncio.run(main())
