from pathlib import Path
from dataclasses import fields
import json,hashlib
from agent_comms.registry_document import RegistryDocument
from agent_comms.comms import Comms
out=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/task-aware520-fork-carry538-receiving-20261002/combined542')
prep=out/'operator-preparation';p=prep/'publication-identity-closure.json';r=json.loads(p.read_text());publisher=prep/'publication-receipt.json'
assert hashlib.sha256(publisher.read_bytes()).hexdigest()==r['raw_publication_sha256']
a=RegistryDocument.from_wire(json.loads((prep/'publication-receipt.originals/registry.json').read_text())).snapshot()
b=Comms(Path('/var/tmp/agent-comms-live-20260927-wzjtqhza'),private_initial_writes=False,private_claim_writes=False).registry.snapshot()
changes=[]
for row in r['owners']:
 name=row['name'];old=a.threads[name];new=b.threads[name]
 changed=[f.name for f in fields(old) if f.name!='process_identity' and getattr(old,f.name)!=getattr(new,f.name)]
 assert set(changed)<= {'turn_generation','last_finished_turn_id'},(name,changed)
 if changed:changes.append({'name':name,'changed_fields':changed,'before':{k:getattr(old,k) for k in changed},'after':{k:getattr(new,k) for k in changed}})
 for f in ('session_file','worktree','model','thinking_level','tags','goal','created_at'):
  assert getattr(old,f)==getattr(new,f),(name,f)
r.update({'all_configuration_and_birth_fields_equal':True,'post_launch_thread_progress_changes':changes,'progress_interpretation':'Canonical turn generation/finished-turn fields advanced after publisher verified exact original settings. This readback does not attribute their trigger or claim absence of autonomous turn effects. Configuration fields did not change.','terminal_evidence':'Completed original publisher receipt and no publisher process required by readback; parent tool disposition recorded separately','schema_equality_scope':'Native6 release unchanged; exact source-to-target declaration adds empty native_fork_creation. Product sourcescca41 and7dd differ by qualified539/540/541/542; no whole-schema/product equality claim.'})
p.write_text(json.dumps(r,indent=2)+'\n')
print(hashlib.sha256(p.read_bytes()).hexdigest())
