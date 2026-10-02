"""Native page custody and source order while growing an existing End admission."""
import asyncio,json,os
from pathlib import Path
from tempfile import TemporaryDirectory
from agent_comms.comms import Comms
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor,TranscriptPage
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory,TranscriptPageView

async def main():
 out=Path(os.environ['RETAINED_END_EVIDENCE']); out.mkdir(exist_ok=False)
 with TemporaryDirectory(dir=out) as directory:
  root=Path(directory)
  os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'),XDG_CONFIG_HOME=str(root/'config'),XDG_STATE_HOME=str(root/'state'),XDG_DATA_HOME=str(root/'data'))
  Comms(root/'wire').messaging.initialize_private_initial_protocol()
  app=ToadApp(project_dir=str(root))
  async with app.run_test(size=(120,38)) as pilot:
   await app.selected_session.wait_content_ready()
   view=app.selected_session.conversation; await view.transcript.suspend()
   cursor=TranscriptCursor('retained-end-page',1)
   events=tuple(AssistantTranscript(f'Record {i}.') for i in range(80))
   history=TranscriptHistory(TranscriptPage(events,cursor,cursor,False,False))
   await view.post(history); await pilot.pause()
   work=history.reserve_source_work()
   page=history.pages[-1]; held_before=tuple(page.children)
   async with view.window.history_lock:
    async with view.window.preserve_history(None):
     page.batch_size=page.stop-page.start+4
     await page.update_fragments(page.fragments,follow=True)
     ordered=tuple(c.fragment for c in page.children)==page.fragments[page.start:page.stop]
     await page.trim(4,older=False)
   held_end=tuple(page.children)
   before_range=page.capture_admission(); before_cost=history.window.document_viewport.materialized_widget_count
   await history._jump_latest()
   # Strong custody witnesses prevent recycled Python ids from proving reuse.
   current=history.pages[-1]
   overlap=[c for c in held_end if c.is_attached and c.parent is current]
   after_order=tuple(c.fragment for c in current.children)==current.fragments[current.start:current.stop]
   receipt={'boundary':'actual native Toad page/end owner/source-order proof; no Agent/provider/public root; not physical41MB acceptance','widen_source_order':ordered,'widen_retained_bodies':sum(c.is_attached for c in held_before),'page_reused':current is page,'overlap_retained_bodies':len(overlap),'before_admission':[before_range.start,before_range.stop],'after_admission':[current.start,current.stop],'after_source_order':after_order,'before_widgets':before_cost,'after_widgets':history.window.document_viewport.materialized_widget_count,'widget_bound':history.window.document_viewport.budget.widget_limit(history.window.size.height),'agent_bound':view.agent is not None,'exception':str(app._exception)}
   (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n'); print(json.dumps(receipt),flush=True)
   history.finish_source_work(work)
   assert not receipt['agent_bound'] and app._exception is None
  await asyncio.get_running_loop().shutdown_default_executor()

if __name__=='__main__': asyncio.run(main())
