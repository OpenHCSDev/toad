"""Read the completed publication; no launch, stop, provider or store writes."""
from pathlib import Path
from dataclasses import replace
import hashlib,json,sys,time
import psutil
out=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/summary-clock555-terminal353-receiving-20261003/new-publication555353')
sys.path.insert(0,str(out/'operator-freeze'))
from publish_retained_summary import ReviewedRetainedSummaryCohort,ROOT,COMMANDS,LINKS
from agent_comms.field_codec import FieldCodec
from agent_comms.registry_document import RegistryDocument
from agent_comms.comms import Comms
from agent_comms.owner_lifecycle import OwnerRestartSelection,OwnerRestartResult
from agent_comms.active_route import read_active_route
from agent_comms.owner_launch import RetainedOwnerLaunch
p=out/'publication-receipt.json'
raw=p.read_bytes(); receipt=json.loads(raw)
assert receipt['phase']=='retained-batch-launched-configurations-verified-public-ui-pending' and receipt['finished']>=receipt['started']
processes=[]
for proc in psutil.process_iter(['pid','cmdline']):
 argv=proc.info['cmdline'] or []
 if len(argv)>1 and Path(argv[1]).name=='execute_retained_summary_foundation.py': processes.append(proc.info['pid'])
assert not processes,processes
cohort=FieldCodec.decode(ReviewedRetainedSummaryCohort,receipt['cohort'])
route=read_active_route(); assert route==replace(cohort.original_route,native_package=cohort.native)
links={name:str((LINKS/name).readlink()) for name in COMMANDS}
assert all(links[name]==str(cohort.target/'bin'/name) for name in COMMANDS)
original=RegistryDocument.from_wire(json.loads(p.with_suffix('.originals').joinpath('registry.json').read_text())).snapshot()
snapshot=Comms(ROOT,private_initial_writes=False,private_claim_writes=False).registry.snapshot()
before=FieldCodec.decode(tuple[OwnerRestartSelection,...],receipt['owners_before'])
results=FieldCodec.decode(tuple[OwnerRestartResult,...],receipt['results'])
assert len(before)==len(results)==19
owners=[]
for old,result in zip(before,results,strict=True):
 assert old.name==result.thread and result.previous_pid==old.process.pid
 current=OwnerRestartSelection.capture(snapshot,result.thread)
 thread=current.require_current(snapshot)
 assert current.identity.incarnation==old.identity.incarnation
 assert current.process.pid==result.pid and current.process!=old.process
 assert thread.process_alive
 config_equal=replace(thread,process_identity=original.threads[old.name].process_identity)==original.threads[old.name]
 launch=RetainedOwnerLaunch.capture(thread,snapshot,interpreter=str(cohort.target/'bin/python'))
 # Credentials remain solely in RAM; export only the declared process witness.
 owners.append({'name':old.name,'before':FieldCodec.encode(old),'after':FieldCodec.encode(current),'alive':True,'settings_equal_except_process':config_equal,'target_interpreter_capture':True})
assert p.read_bytes()==raw
result={'state':'Published target identity/link/route readback complete; ordinary default physical verification remains parent-owned','observed_at':time.time(),'raw_publication_phase':receipt['phase'],'raw_publication_sha256':hashlib.sha256(raw).hexdigest(),'publisher_duration_seconds':receipt['finished']-receipt['started'],'publisher_processes_remaining':processes,'target_prefix':str(cohort.target),'owners':owners,'owner_count':len(owners),'all_same_thread_births':True,'all_new_process_identities_alive':True,'all_settings_equal_except_process':all(x['settings_equal_except_process'] for x in owners),'five_links':links,'route':FieldCodec.encode(route),'same_original_root_and_root_id':True,'source_target_schema_equal':True,'source_target_product_equal':False,'public_writes':0,'stops':0,'starts':0,'provider_calls':0,'native_inputs':0,'publication_repeated':False,'physical_verification':'Pending parent/Heisenberg terminal-authorized run; no claim from this readback'}
path=out/'publication-identity-closure.json'
assert not path.exists();path.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('owners','route','five_links')},indent=2))
