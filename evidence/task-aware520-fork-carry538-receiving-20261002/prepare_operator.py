"""Freeze existing receiving owner and exact operands; no live stores acquired."""
from pathlib import Path
import hashlib,json,os,shlex,sys
from dataclasses import fields
wt=Path('/home/ts/wt/toad-prompt-action-owner-20261002')
out=wt/'.artifacts/task-aware520-fork-carry538-receiving-20261002'
owner=json.loads((out/'ownership.json').read_text());target=Path(owner['prefix'])
source=wt/'.artifacts/runtime-selected-publication530-sidebar323-20261002'
assert sys.executable==str(target/'bin/python')
manifest=json.loads((out/'operator-manifest.json').read_text());operator=Path(manifest['operator_root'])
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,value in manifest['files'].items():assert digest(operator/name)==value,name
sys.path.insert(0,str(operator))
from agent_comms.active_route import read_active_route
from agent_comms.field_codec import FieldCodec
from native_schema_carry import NativeSchemaDeclaration
from publish_retained_summary import ReviewedArtifact,ReviewedRetainedSummaryCohort
original=FieldCodec.decode(NativeSchemaDeclaration,json.loads((out/'original-declaration.json').read_text()))
current=FieldCodec.decode(NativeSchemaDeclaration,json.loads((out/'target-declaration.json').read_text()))
assert current==NativeSchemaDeclaration.observe()
original.require_carry_target(current)
assert original.goal==current.goal
changed=[field.name for field in fields(original) if getattr(original,field.name)!=getattr(current,field.name)]
assert set(changed)=={'compaction','compaction_columns'},changed
additions=current.empty_journal_members(original)
assert set(additions)=={'native_fork_creation'} and all(not rows for _,rows in additions.values())
output=out/'operator-preparation';output.mkdir(mode=0o700)
def save(name,data):
 p=output/name;p.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n');return p
def artifact(p):return ReviewedArtifact(p,digest(p))
cohort=ReviewedRetainedSummaryCohort(target=target,source_interpreter=source/'bin/python',current_prefix=source,original_route=read_active_route(),native=Path(owner['native']),activation=artifact(target/'activation.json'),source_proof=artifact(out/'source-proof.json'),actual_gates=tuple(artifact(out/'qualified-source-gates'/n) for n in ('520-READY.json','538-receipt.json','538-native5-receipt.json')))
cohort.require_original()
plan=save('review-plan.json',FieldCodec.encode(cohort))
relation=save('declaration-relation.json',{'source':manifest['original_source'],'target':owner['core'],'source_release_versions':original.release_versions,'target_release_versions':current.release_versions,'whole_schema_equal':False,'changed_declaration_fields':changed,'declared_empty_members':FieldCodec.encode(additions),'runtime_binding_coordination_goal_metadata_unchanged':True,'source_product_equal':False,'live_original_stores_opened':False,'live_original_stores_changed':False,'retroactive_creation_evidence':False})
carry=output/'reviewed-native-carry.json'
runtime=output/'runtime-installation.json'
publication=output/'publication-receipt.json'
commands={
 'native_carry_prepare':[str(target/'bin/python'),str(operator/'native_schema_carry.py'),'--root',str(cohort.original_route.root),'--candidate',str(output/'native-carry-candidate'),'--original-declaration',str(out/'original-declaration.json'),'--original-python',str(source/'bin/python'),'--plan',str(carry)],
 'bind_reviewed_runtime':[str(target/'bin/python'),str(out/'bind_carry.py'),'--carry-plan',str(carry),'--runtime-installation',str(runtime)],
 'parent_execute_once':[str(target/'bin/python'),str(operator/'execute_retained_summary_foundation.py'),'--review-plan',str(plan),'--runtime-installation',str(runtime),'--receipt',str(publication),'--execute']}
receipt=save('preparation-receipt.json',{'state':'SOURCE/OPERATOR READY; PARENT ORIGINAL STOPPED MATCHED CARRY NOT ACQUIRED OR EXECUTED','source_prefix':str(source),'target_prefix':str(target),'operator_manifest':str(out/'operator-manifest.json'),'operator_manifest_sha256':digest(out/'operator-manifest.json'),'operator_members':len(manifest['files']),'source_core':manifest['original_source'],'target_core':owner['core'],'runtime_member':'CarryNativeRuntimeInstallation','optional_strategy_default':False,'original_stopped_carry_plan_present':False,'native_version':original.version,'whole_schema_equal':False,'declared_new_members_start_empty':list(additions),'plan_sha256':digest(plan),'source_proof_sha256':cohort.source_proof.sha256,'declaration_relation_sha256':digest(relation),'commands':{k:shlex.join(v) for k,v in commands.items()},'execution_condition':'Parent alone acquires/reviews exact original stopped matched source via existing owner/kernel custody. Carry candidate/hashes must match originals at installed stopped boundary; existing publisher validates all original settings and refuses drift. Do not execute without that review. No original input retry/reset/retroproof or public operation by receiving owner.','public_stops':0,'public_starts':0,'public_writes':0})
print(receipt.read_text())
