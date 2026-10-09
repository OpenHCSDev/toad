import asyncio,json,os,sys
from pathlib import Path
from agent_comms.comms import Comms
from textual._compositor import Compositor
from textual.containers import VerticalGroup, HorizontalGroup
from textual.geometry import Size
from textual._measurement import arrangement_depends_on_available_height
from textual.widgets import Static
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
  native_flows=[]
  for node in (*auto.walk_children(), auto, *tool.walk_children()):
   if not isinstance(node, (VerticalGroup, HorizontalGroup)): continue
   original_flow=node.layout.arrange
   flow_calls=[]
   def flow(*args, _original=original_flow, _calls=flow_calls, **kwargs):
    _calls.append(args[2].height)
    return _original(*args, **kwargs)
   node.layout.arrange=flow;node._arrangement_cache.clear()
   layouts=[node.arrange(Size(node.size.width, available)) for available in range(80,88)]
   del node.layout.arrange
   placements=[tuple((item.widget, item.region) for item in layout.placements) for layout in layouts]
   native_flows.append(dict(kind=type(node).__name__,width=node.size.width,dependent=arrangement_depends_on_available_height(node),native_flow_calls=len(flow_calls),all_placements_equal=all(p==placements[0] for p in placements),cache_policy=node.CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT,children=[type(c).__name__ for c in node.displayed_children]))
  independent=next(node for node in auto.walk_children() if type(node).__name__=='DiffScrollContainer')
  reference=tuple((item.widget,item.region) for item in independent.arrange(Size(independent.size.width,80)).placements)
  leaf=independent.displayed_children[0]
  prior_padding=leaf.styles.padding
  leaf.styles.padding=(prior_padding.top+1,prior_padding.right,prior_padding.bottom+1,prior_padding.left)
  await pilot.pause()
  styled=tuple((item.widget,item.region) for item in independent.arrange(Size(independent.size.width,80)).placements)
  assert styled!=reference, 'native child padding must invalidate the existing arrangement'
  prior_height=leaf.styles.height
  leaf.styles.height='1fr'
  await pilot.pause()
  assert arrangement_depends_on_available_height(independent)
  relative=[tuple((item.widget,item.region) for item in independent.arrange(Size(independent.size.width,height)).placements) for height in (80,87)]
  assert relative[0]!=relative[1], 'relative child geometry must use available height'
  leaf.styles.height=prior_height;leaf.styles.padding=prior_padding;await pilot.pause()
  before_membership=independent.arrange(Size(independent.size.width,80))
  extra=Static('native membership addition');await independent.mount(extra);await pilot.pause()
  after_membership=independent.arrange(Size(independent.size.width,80))
  assert any(item.widget is extra for item in after_membership.placements)
  assert all(item.widget is not extra for item in before_membership.placements)
  await extra.remove();await pilot.pause()
  retired=independent.arrange(Size(independent.size.width,80))
  assert all(item.widget is not extra for item in retired.placements)
  class ContextFlow(HorizontalGroup):
   def pre_layout(self,layout):
    super().pre_layout(layout)
  unknown=ContextFlow(Static('unknown native layout hook'))
  await auto.mount(unknown);await pilot.pause()
  assert arrangement_depends_on_available_height(unknown)
  family=[]
  for Flow in (VerticalGroup,HorizontalGroup):
   owner=Flow(Static('first original native row'),Static('second original native row'))
   await auto.mount(owner);await pilot.pause()
   assert not arrangement_depends_on_available_height(owner)
   flow_calls=[];native_arranger=owner.layout.arrange
   def counted(*args,_original=native_arranger,**kwargs):
    flow_calls.append(args[2].height);return _original(*args,**kwargs)
   owner.layout.arrange=counted;owner._arrangement_cache.clear()
   layouts=[owner.arrange(Size(owner.size.width,height)) for height in range(80,88)]
   del owner.layout.arrange
   placements=[tuple((p.widget,p.region) for p in layout.placements) for layout in layouts]
   assert all(p==placements[0] for p in placements)
   assert len(flow_calls)==(1 if owner.CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT else 8)
   owner.displayed_children[0].styles.height='1fr';await pilot.pause()
   assert arrangement_depends_on_available_height(owner)
   family.append(dict(kind=Flow.__name__,calls=len(flow_calls),equal_placements=True,relative_height_rejected=True))
   await owner.remove();await pilot.pause()
  (root/'family.json').write_text(json.dumps(family,indent=2)+'\n')
  (root/'invalidation.json').write_text(json.dumps(dict(padding_invalidated=True,relative_geometry_changed=True,membership_added=True,membership_retired=True,unknown_hook_dependent=True,textual_path=__import__('textual').__file__,agent_bound=False,app_exception=str(app._exception)),indent=2)+'\n')
  for record in native_flows:
   expected=1 if record['cache_policy'] and not record['dependent'] else 8
   assert record['native_flow_calls']==expected,record
   assert record['all_placements_equal'],record
  (root/'native-flows.json').write_text(json.dumps(native_flows,indent=2)+'\n')
  print(json.dumps(native_flows),flush=True)
  mounted=[s for s in calls if any('textual_diff_view/' in f[0] and f[1]=='on_mount' for f in s)]
  receipt={'states':states,'all_native_arrangements':len(calls),'native_diff_mount_arrangements':len(mounted),'native_diff_mount_stacks':mounted,'agent_bound':False,'exception':str(app._exception),'boundary':'Actual native Toad/library mount and committed Resize control; no Agent/provider or public root; not saved41MB installed readiness'}
  (root/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({k:v for k,v in receipt.items() if k!='native_diff_mount_stacks'}),flush=True)
  assert states[0]['auto_split'] and not states[1]['auto_split'] and states[2]['auto_split'],states
  assert [s['patch_split'] for s in states]==[True,False,True],states
  assert all(not s['padded_split'] and not s['fixed_split'] for s in states) and app._exception is None
  Compositor._arrange_root=original
 await asyncio.get_running_loop().shutdown_default_executor()
if __name__=='__main__':asyncio.run(main())
