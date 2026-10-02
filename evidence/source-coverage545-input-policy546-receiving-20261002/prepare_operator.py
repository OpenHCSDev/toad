"""Prepare the existing preserve-only publisher; no original store or process writes."""
from pathlib import Path
import hashlib,json,shlex,subprocess,sys
wt=Path('/home/ts/wt/toad-prompt-action-owner-20261002')
out=wt/'.artifacts/source-coverage545-input-policy546-receiving-20261002'
owner=json.loads((out/'ownership.json').read_text()); target=Path(owner['prefix'])
source=wt/'.artifacts/runtime-native-read532-534-retirement325-20261002'
assert sys.executable==str(target/'bin/python')
manifest=json.loads((out/'operator-manifest.json').read_text()); operator=Path(manifest['operator_root'])
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,sha in manifest['files'].items(): assert digest(operator/name)==sha,name
sys.path.insert(0,str(operator))
from agent_comms.active_route import read_active_route
from agent_comms.field_codec import FieldCodec
from native_schema_carry import NativeSchemaDeclaration
from runtime_installation import PreserveRuntimeInstallation
from publish_retained_summary import ReviewedArtifact,ReviewedRetainedSummaryCohort
program="import sys,json; sys.path.insert(0,sys.argv[1]); from native_schema_carry import NativeSchemaDeclaration; from agent_comms.field_codec import FieldCodec; print(json.dumps(FieldCodec.encode(NativeSchemaDeclaration.observe())))"
raw=subprocess.check_output([str(source/'bin/python'),'-c',program,str(operator)],text=True)
original=FieldCodec.decode(NativeSchemaDeclaration,json.loads(raw)); current=NativeSchemaDeclaration.observe()
assert original==current,'Actual source/target declaration differs; preserve installation is not admitted'
output=out/'operator-preparation'; output.mkdir(mode=0o700,exist_ok=True)
def save(name,data):
 p=output/name;p.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n');return p
def artifact(p): return ReviewedArtifact(p,digest(p))
save('original-declaration.json',FieldCodec.encode(original)); save('target-declaration.json',FieldCodec.encode(current))
cohort=ReviewedRetainedSummaryCohort(target=target,source_interpreter=source/'bin/python',current_prefix=source,original_route=read_active_route(),native=Path(owner['native']),activation=artifact(target/'activation.json'),source_proof=artifact(out/'source-proof.json'),actual_gates=tuple(artifact(out/'qualified-source-gates'/n) for n in ('527-functional02.json','527-prefix-capability.json','331-scoped05.json','545546-original540-floor.json')))
cohort.require_original()
plan=save('review-plan.json',FieldCodec.encode(cohort))
relation=save('declaration-relation.json',{'source':manifest['original_source'],'target':owner['core'],'source_release_versions':original.release_versions,'target_release_versions':current.release_versions,'whole_schema_equal':True,'source_product_equal':False,'carry_reset_required':False,'original_stores_opened':False,'public_changes':0})
runtime=save('runtime-installation.json',FieldCodec.encode(PreserveRuntimeInstallation(goal_schema=original.goal)))
publication=output/'publication-receipt.json'; assert not publication.exists(),'Original publication needs disposition, never repeat'
command=shlex.join([str(target/'bin/python'),str(operator/'execute_retained_summary_foundation.py'),'--review-plan',str(plan),'--runtime-installation',str(runtime),'--receipt',str(publication),'--execute'])
receipt=save('preparation-receipt.json',{'state':'READY original preserve-only operation; NOT EXECUTED','source_prefix':str(source),'target_prefix':str(target),'source_core':manifest['original_source'],'target_core':owner['core'],'operator_manifest':str(out/'operator-manifest.json'),'operator_manifest_sha256':digest(out/'operator-manifest.json'),'operator_members':len(manifest['files']),'whole_schema_equal':True,'product_equal':False,'runtime_member':'PreserveRuntimeInstallation','runtime_installation_sha256':digest(runtime),'plan_sha256':digest(plan),'source_proof_sha256':cohort.source_proof.sha256,'declaration_relation_sha256':digest(relation),'commands':{'parent_execute_once':command},'execution_condition':'Parent alone, after user client closes normally and fresh original audience idle/client0; existing executor checks exact hashes, original route/links and audience before admission. Capture launches and preserve originals inside existing stopped lifetime. No manual stop, carry/reset/input replay. Existing receipt means disposition, never repeat.','public_effects':0})
print(receipt.read_text())
