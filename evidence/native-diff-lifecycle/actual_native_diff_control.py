import asyncio,json,os,sys
from pathlib import Path
from agent_comms.comms import Comms
from textual._compositor import Compositor
from toad.app import ToadApp
from toad.widgets.diff_view import DiffView
from toad.widgets.patch_diff import PatchDiffView
from toad.widgets.tool_call import ToolCall
from toad.acp.status import ToolCallStatus
from acp.schema import ToolCall as ACPToolCall

async def main():
 root=Path(os.environ['DIFF_GEOMETRY_EVIDENCE']);root.mkdir(exist_ok=False)
 os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'),XDG_CONFIG_HOME=str(root/'config'),XDG_STATE_HOME=str(root/'state'),XDG_DATA_HOME=str(root/'data'))
 Comms(root/'wire').messaging.initialize_private_initial_protocol()
 calls=[];original=Compositor._arrange_root
 def arranged(owner,*args,**kwargs):
  f=sys._getframe(1);frames=[]
  while f:
   frames.append([f.f_code.co_filename,f.f_code.co_name,f.f_lineno]);f=f.f_back
  calls.append(frames);return original(owner,*args,**kwargs)
 app=ToadApp(project_dir=str(root))
 async with app.run_test(size=(120,38)) as pilot:
  await app.selected_session.wait_content_ready();view=app.selected_session.conversation
  assert view.agent is None;await view.transcript.suspend()
  Compositor._arrange_root=arranged
  auto=DiffView('a.py','b.py','print(1)\n','print(2)\n',auto_split=True,split=False)
  fixed=DiffView('a.py','b.py','print(1)\n','print(2)\n',auto_split=False,split=False)
  source='--- a.py\n+++ b.py\n@@ -1 +1 @@\n-print(1)\n+print(2)\n'
  call=ACPToolCall.model_validate({'toolCallId':'diff-geometry-patch','title':'Native patch','kind':'edit','status':'completed','content':[{'type':'content','content':{'type':'resource','resource':{'uri':'file:///native-control.patch','mimeType':'text/x-diff','text':source}}}]})
  tool=ToolCall(ToolCallStatus.from_acp(call))
  padded=DiffView('a.py','b.py','print(1)\n','print(2)\n',auto_split=True,split=False);padded.styles.padding=(0,22)
  await view.post(auto);await view.post(fixed);await view.post(tool);tool.set_expanded(True);await tool.output.sync();await view.post(padded);await pilot.pause()
  async with asyncio.timeout(10):
   while not tool.query(PatchDiffView):await pilot.pause(.05)
  patch=tool.query_one(PatchDiffView);patch.auto_split=True
  await pilot.resize_terminal(119,38);await pilot.resize_terminal(120,38);await pilot.pause()
  states=[{'phase':'wide-mounted','auto_split':auto.split,'fixed_split':fixed.split,'width':auto.size.width,'patch_split':patch.split,'padded_split':padded.split,'padded_width':padded.size.width}]
  await pilot.resize_terminal(40,38);await pilot.pause()
  states.append({'phase':'narrow','auto_split':auto.split,'fixed_split':fixed.split,'width':auto.size.width,'patch_split':patch.split,'padded_split':padded.split,'padded_width':padded.size.width})
  await pilot.resize_terminal(120,38);await pilot.pause()
  states.append({'phase':'wide-return','auto_split':auto.split,'fixed_split':fixed.split,'width':auto.size.width,'patch_split':patch.split,'padded_split':padded.split,'padded_width':padded.size.width})
  mounted=[s for s in calls if any('textual_diff_view/' in f[0] and f[1]=='on_mount' for f in s)]
  receipt={'states':states,'all_native_arrangements':len(calls),'native_diff_mount_arrangements':len(mounted),'native_diff_mount_stacks':mounted,'agent_bound':False,'exception':str(app._exception),'boundary':'Actual native Toad/library mount and committed Resize control; no Agent/provider or public root; not saved41MB installed readiness'}
  (root/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({k:v for k,v in receipt.items() if k!='native_diff_mount_stacks'}),flush=True)
  assert states[0]['auto_split'] and not states[1]['auto_split'] and states[2]['auto_split'],states
  assert [s['patch_split'] for s in states]==[True,False,True],states
  assert all(not s['padded_split'] and not s['fixed_split'] for s in states) and app._exception is None
  Compositor._arrange_root=original
 await asyncio.get_running_loop().shutdown_default_executor()
if __name__=='__main__':asyncio.run(main())
