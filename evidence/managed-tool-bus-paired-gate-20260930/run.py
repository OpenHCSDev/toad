"""Run the two dispatched installed journeys; preserve short owned fixture roots."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import os,json,time,importlib.metadata as md
base=Path(__file__).parent
sys.path.insert(0,str(base/'deps'))
tests=Path('/home/ts/wt/comms-cleanup-live-integration-20260929/tests')
sys.path.insert(0,str(tests))
import pytest
from agent_comms.acp import CommsClient
from agent_comms.acp_extension import decode_updates
from agent_comms.field_codec import FieldCodec
import agent_comms
stage=Path('/home/ts/.local/share/agent-comms/runtime-managed-tool-bus-custody-20260930')
activation=json.loads((stage/'activation.json').read_text())
assert Path(sys.prefix)==stage
assert Path(agent_comms.__file__).is_relative_to(stage)
for package,pin in activation['pins'].items():
 assert json.loads(md.distribution(package).read_text('direct_url.json'))['vcs_info']['commit_id']==pin
assert md.version('agent-client-protocol')=='0.12.1'
for key in ['PYTHONPATH','AGENT_COMMS_ROOT','AGENT_COMMS_RUNTIME_ROOT','AGENT_COMMS_ACP_LAUNCHER','AGENT_COMMS_THREAD','AGENT_COMMS_MANAGED','AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID','AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE','PI_AGENT_ID','PI_PARENT_ID','PI_TASK','PI_WORKTREE','PI_PROMPT']:
 os.environ.pop(key,None)
os.environ['PYTHONPATH']=str(tests)  # Children can import tests only; no production source override.
os.environ['PI_COMPACTION_TEST_PACKAGE']=activation['native_package']
os.environ['PATH']=str(stage/'bin')+os.pathsep+os.environ['PATH']
origin=time.monotonic()
connect=CommsClient.on_connect
class Evidence:
 def pytest_collection_modifyitems(self,items):
  assert len(items)==2
  for index,item in enumerate(items,1):
   definitions=item._fixtureinfo.name2fixturedefs['tmp_path']
   def persistent_root(case=index):
    root=base/f'f{case}';root.mkdir(mode=0o700,exist_ok=False)
    yield root  # Existing workflow finalizers retire owners; preserve journal/UNKNOWN evidence.
   # Only the existing tmp_path provider is relocated, retaining the original two workflows.
   definitions[-1].func=persistent_root
 def pytest_runtest_setup(self,item):
  name=item.nodeid
  def observed_connect(attachment,client):
   callback=client.session_update
   async def observed_update(**kwargs):
    facts=tuple(decode_updates(kwargs['update'].get('_meta')))
    with (base/'acp-events.jsonl').open('a') as output:
     output.write(json.dumps({'test':name,'elapsed_seconds':time.monotonic()-origin,'session_id':kwargs.get('session_id',kwargs.get('sessionId')),'facts':FieldCodec.encode(facts)})+'\n')
    return await callback(**kwargs)
   client.session_update=observed_update
   return connect(attachment,client)
  CommsClient.on_connect=observed_connect
 def pytest_runtest_teardown(self,item):
  CommsClient.on_connect=connect
 def pytest_runtest_logreport(self,report):
  with (base/'test-events.jsonl').open('a') as out:
   out.write(json.dumps({'nodeid':report.nodeid,'when':report.when,'outcome':report.outcome,'duration_seconds':report.duration,'elapsed_seconds':time.monotonic()-origin})+'\n')
preflight={'runtime':str(stage),'python':sys.executable,'production_origin':agent_comms.__file__,'activation':activation,'test_only_dependencies':str(base/'deps'),'production_source_pythonpath':False,'fixture_roots':[str(base/'f1'),str(base/'f2')],'source_tests':str(tests),'provider_authorization':'Controlled localhost2+5POSTs only, no paid/public input','instrumentation':'Timestamp existing session_update facts using decode_updates and FieldCodec; no semantic state map','started_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
(base/'preflight.json').write_text(json.dumps(preflight,indent=2)+'\n')
args=['-o','addopts=','--import-mode=importlib','-s','-q',str(tests/'test_native_fork_first_input.py')+'::test_underbudget_physical_native_owner_answers_without_compaction[fork_owner]',str(tests/'test_native_channel_reply_roundtrip.py')+'::test_native_channel_reply_automatically_reaches_original_sender[saved-restart]']
code=pytest.main(args,plugins=[Evidence()])
(base/'terminal-receipt.json').write_text(json.dumps({'exit_code':int(code),'elapsed_seconds':time.monotonic()-origin,'tests':args[-2:],'one_execution':True,'manual_replays':0,'paid_calls':0,'public_mutations':0,'limitations':'No tool-running coverage or real-provider queue/reasoning split; original400 budget failures independent'},indent=2)+'\n')
raise SystemExit(code)
