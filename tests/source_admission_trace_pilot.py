import asyncio,json,os
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from agent_comms.comms import Comms
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor,TranscriptPage
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory

async def main():
 out=Path(os.environ['SOURCE_ADMISSION_EVIDENCE']); out.mkdir(exist_ok=False)
 with TemporaryDirectory(dir=out) as directory:
  root=Path(directory)
  os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'),XDG_CONFIG_HOME=str(root/'config'),XDG_STATE_HOME=str(root/'state'),XDG_DATA_HOME=str(root/'data'))
  Comms(root/'wire').messaging.initialize_private_initial_protocol()
  app=ToadApp(project_dir=str(root))
  async with app.run_test(size=(120,38)) as pilot:
   await app.selected_session.wait_content_ready()
   view=app.selected_session.conversation
   await view.transcript.suspend()
   cursor=TranscriptCursor('owned-fixed-page',1)
   events=tuple(AssistantTranscript(f'Record {i}.') for i in range(80))
   history=TranscriptHistory(TranscriptPage(events,cursor,cursor,False,False))
   page=history.pages[0]; constructed=[]
   original=page._body
   def body(fragment):
    constructed.append(page.fragments.index(fragment)); return original(fragment)
   page._body=body
   await view.post(history)
   await pilot.pause()
   view.window.focus()
   states=[]
   for phase,key in [('up','pageup'),('down','pagedown'),('reverse','pageup'),('end','end')]:
    for step in range(15 if phase!='end' else 1):
     await pilot.press(key); await pilot.pause(.03)
     states.append({'phase':phase,'step':step,'range':[page.start,page.stop], 'fragment_count':history.fragment_count,'widgets':history.widget_count,'widget_bound':history.widget_limit,'y':view.window.scroll_y,'maximum':view.window.max_scroll_y,'native_body_evictions':view.window.document_viewport.body_evictions,'constructs':len(constructed)})
   await pilot.pause(.3)
   counts=Counter(constructed)
   receipt={'boundary':'actual native Toad/Pilot source-admission diagnostic; no Agent/provider or public root; not saved41MB physical acceptance','agent_bound':view.agent is not None,'constructor_calls':len(constructed),'distinct_source_fragments':len(counts),'reconstructed_source_fragments':{str(k):v for k,v in counts.items() if v>1},'native_body_evictions':view.window.document_viewport.body_evictions,'source_fragments':len(page.fragments),'states':states,'exception':str(app._exception)}
   (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
   print(json.dumps({k:v for k,v in receipt.items() if k!='states'}),flush=True)
   assert not receipt['agent_bound'] and app._exception is None
  await asyncio.get_running_loop().shutdown_default_executor()

if __name__=='__main__': asyncio.run(main())
