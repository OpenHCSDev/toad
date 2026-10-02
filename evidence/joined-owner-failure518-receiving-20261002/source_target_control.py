"""One original-c601/merged-target native owner, acquired failure and CLI handoff.

Uses actual installed lifecycle/worker/SubscribeRuntimeRequest and the existing
RAM/OFD restore helper. No native input, provider call or public mutation.
"""
from pathlib import Path
import asyncio, errno, hashlib, json, os, subprocess, sys, time
from dataclasses import replace
import agent_comms
from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.goal_states import BlockedGoal
from agent_comms.goals import Goal
from agent_comms.owner_cutover import StoppedOwnerInstallation
from agent_comms.owner_launch import RetainedOwnerLaunch
from agent_comms.owner_restart import StoppedOwnerFailure, OwnerRestartHandoff
from agent_comms.private_nk_entrypoint import PrivateNkLaunch
from agent_comms.runtime import socket_path
from agent_comms.runtime_requests import SubscribeRuntimeRequest
from agent_comms.threads import Thread

out=Path(__file__).parent; meta=json.loads((out/'ownership.json').read_text())
target=Path(meta['prefix']); original=Path(meta['original_prefix']); root=out/'source-target-private02'
assert Path(sys.prefix)==target and 'site-packages' in str(agent_comms.__file__)
assert not root.exists();root.mkdir(mode=0o700)
comms=Comms(root); root_id=comms.messaging.initialize_private_initial_protocol()
private=PrivateNkLaunch(root, root_id, Path(meta['native']), None)
comms.owners.pin_private_nk_launch(root, root_id, Path(meta['native']))
sourceenv=dict(os.environ); sourceenv.pop('PYTHONPATH',None)
sourceenv.update(PATH=str(original/'bin')+os.pathsep+sourceenv['PATH'],VIRTUAL_ENV=str(original),
 PI_CODING_AGENT_DIR=str(root/'original-policy'),AGENT_COMMS_NATIVE_CONFIG_DIR=str(root/'original-credentials'),
 AGENT_COMMS_AGENT_ARGS='--offline --no-tools',FIXTURE_ORIGINAL_CREDENTIAL='RAM-only-fixture')
private.apply_environment(sourceenv)
for path in (root/'original-policy',root/'original-credentials'):path.mkdir()
comms.registry.declare(Thread('source-owner',frozenset({'private518'}),str(root),task='Retain original source configuration',
 model='openai-codex/gpt-6.1-sol',thinking_level='off',goal=Goal('No input replay','protected518',state=BlockedGoal('Preserved'))))
targetenv=dict(os.environ);targetenv.pop('PYTHONPATH',None);private.apply_environment(targetenv)
targetenv.update(PATH=str(target/'bin')+os.pathsep+targetenv['PATH'],VIRTUAL_ENV=str(target))
sys.path.insert(0,'/home/ts/wt/comms-stopped-cutover-failure-custody-20261002/tools/cutover')
from cutover_child import restore_stopped_batch

async def attached(thread):
 deadline=time.monotonic()+10
 while not socket_path(root,thread.pid).exists():
  assert thread.process_alive
  assert time.monotonic()<deadline
  await asyncio.sleep(.02)
 async with asyncio.timeout(10):
  reader,writer=await asyncio.open_unix_connection(socket_path(root,thread.pid),limit=8*1024*1024)
  try:
   writer.write((json.dumps(SubscribeRuntimeRequest(thread=thread.name).to_wire())+'\n').encode());await writer.drain()
   while line:=await reader.readline():
    packet=json.loads(line);assert 'error' not in packet,packet
    if 'ready' in packet:return
   raise AssertionError('Owner closed before actual ready publication')
  finally:writer.close();await writer.wait_closed()

def unavailable():
 return subprocess.run([sys.executable,'-c',"import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)",str(root/'.wire.lock')],capture_output=True).returncode!=0

class ControlledInstallFailure(StoppedOwnerInstallation):
 def require_selection(self,snapshot,owners):pass
 def after_stopped(self,lifecycle):raise OSError(errno.EXDEV,'Controlled unchanged-original installation failure')
 def recover(self,stopped):return restore_stopped_batch(stopped)

started=time.monotonic(); steps=[]
try:
 launched=subprocess.run([str(original/'bin/python'),'-c',"from agent_comms.comms import wire; wire().owners.start('source-owner')"],env=sourceenv,capture_output=True,text=True,check=True)
 source=comms.registry.require('source-owner');asyncio.run(attached(source))
 observed=RetainedOwnerLaunch.capture(source,comms.registry.snapshot(),interpreter=str(original/'bin/python'))
 source_files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.jsonl')}
 steps.append('Original c601 actual native worker attached with original configuration')
 try:
  comms.owners.restart_owners(['source-owner'],agent_bin=str(target/'bin/pi-comms-native'),cutover=ControlledInstallFailure())
 except StoppedOwnerFailure as failure:
  assert isinstance(failure.__cause__,OSError) and failure.__cause__.errno==errno.EXDEV
  assert not source.process_alive and unavailable()
  handoff=FieldCodec.decode(OwnerRestartHandoff,FieldCodec.encode(failure.stopped.handoff))
  assert handoff.owners[0].launch.configuration==observed.configuration
  try:restored=failure.recover()
  finally:failure.abandon()
 else:raise AssertionError('No acquired stopped failure')
 assert not unavailable(); recovered=comms.registry.require('source-owner');asyncio.run(attached(recovered))
 restored_launch=RetainedOwnerLaunch.capture(recovered,comms.registry.snapshot(),interpreter=str(original/'bin/python'))
 assert restored_launch.configuration==observed.configuration
 assert restored_launch.arguments==observed.arguments and restored_launch.binary==observed.binary
 assert restored_launch.environment['FIXTURE_ORIGINAL_CREDENTIAL']==observed.environment['FIXTURE_ORIGINAL_CREDENTIAL']
 assert replace(recovered,process_identity=source.process_identity)==source
 steps.append('Target handoff decoded by original c601 through same RAM/OFD child; exact original configuration restored')
 command=[str(target/'bin/agent-comms'),'--root',str(root),'restart','--name','source-owner','--agent-bin',str(target/'bin/pi-comms-native')]
 cli=subprocess.run(command,env=targetenv,capture_output=True,text=True,check=True);payload=json.loads(cli.stdout)
 assert len(payload['restarted'])==1
 current=comms.registry.require('source-owner');asyncio.run(attached(current))
 final=RetainedOwnerLaunch.capture(current,comms.registry.snapshot(),interpreter=str(target/'bin/python'))
 assert final.configuration.native_config==observed.configuration.native_config
 assert final.configuration.agent_directory==observed.configuration.agent_directory
 assert final.arguments==observed.arguments and current.goal==source.goal
 assert final.environment['FIXTURE_ORIGINAL_CREDENTIAL']==observed.environment['FIXTURE_ORIGINAL_CREDENTIAL']
 assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in source_files.items())
 assert not list(root.rglob('*.input-proof'))
 steps.append('Normal installed target CLI restarted original c601 owner into joined target; original native config/settings/goal retained')
 receipt={'state':'PASS','original_prefix':str(original),'target_prefix':str(target),'target_module':str(agent_comms.__file__),
  'original_core':'c6019afd34313db81504a364e3cc4024470a3034','target_core':meta['core'],'steps':steps,
  'seconds':time.monotonic()-started,'actual_source_to_target_handoff':True,'original_config_retained':True,
  'source_fields_qualified':['RestartEnvironment.native_config','RestartEnvironment.agent_directory','RetainedOwnerLaunch.configuration'],
  'original_input_proofs_unchanged':True,'provider_calls':0,'native_inputs':0,'public_mutations':0,'source_overlay':False}
 (out/'source-target-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)
finally:
 current=comms.registry.require('source-owner')
 if current.process_alive:comms.owners.stop(current.name)
 assert not comms.registry.require('source-owner').process_alive
