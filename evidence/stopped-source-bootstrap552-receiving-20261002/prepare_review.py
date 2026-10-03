"""Prepare original declaration/cohort operands; no public effects or execution."""
from pathlib import Path
import hashlib,json,subprocess,sys
from agent_comms.private_path import PrivateDirectoryRole
base=Path(__file__).resolve().parent
base.mkdir(mode=PrivateDirectoryRole.permissions, parents=True, exist_ok=True)
PrivateDirectoryRole.require(base.lstat())
out=base.parent
owner=json.loads((out/'ownership.json').read_text())
target=Path(owner['prefix'])
source=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/runtime-native-read532-534-retirement325-20261002')
assert sys.executable==str(target/'bin/python')
operator=base/'operator-final552'
sys.path.insert(0,str(operator))
from agent_comms.active_route import read_active_route
from agent_comms.field_codec import FieldCodec
from native_schema_carry import NativeSchemaDeclaration
from runtime_installation import PreserveRuntimeInstallation
from publish_retained_summary import ReviewedArtifact,ReviewedRetainedSummaryCohort
program="import sys,json; sys.path.insert(0,sys.argv[1]); from native_schema_carry import NativeSchemaDeclaration; from agent_comms.field_codec import FieldCodec; print(json.dumps(FieldCodec.encode(NativeSchemaDeclaration.observe())))"
original=FieldCodec.decode(NativeSchemaDeclaration,json.loads((base/'pre552-provisional'/'original-declaration.json').read_text()))
current=NativeSchemaDeclaration.observe()
assert original==current,'Original/target declarations differ; preserve-only is not qualified'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,value):
 p=base/name;p.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n');return p
def artifact(p):return ReviewedArtifact(p,digest(p))
cohort=ReviewedRetainedSummaryCohort(target=target,source_interpreter=source/'bin/python',current_prefix=source,original_route=read_active_route(),native=Path(owner['native']),activation=artifact(target/'activation.json'),source_proof=artifact(out/'source-proof.json'),actual_gates=(artifact(out/'lifetime-recovery-receipt.json'),artifact(Path('/home/ts/wt/comms-task-aware-native-bundle-20261002/evidence/native-operation-custody-20261002/corrected-owner-terminal.json')),artifact(Path('/home/ts/.cache/agent-scratch/context-explorer309-return-2809-20261002/capture/receipt.json')),artifact(Path('/home/ts/wt/comms-task-aware-native-bundle-20261002/evidence/stopped-source-recovery-footprint-20261002/final552-installed-file-mode-recovery-receipt.json'))))
# Public mutation is not performed. The ordinary executor validates the original
# route/link/client/audience resources only after final source-deployment review.
save('original-declaration.json',FieldCodec.encode(original))
save('target-declaration.json',FieldCodec.encode(current))
save('review-plan.json',FieldCodec.encode(cohort))
runtime=save('runtime-installation.json',FieldCodec.encode(PreserveRuntimeInstallation(original.goal)))
save('declaration-relation.json',{'whole_declared_schema_equal':True,'product_equal':False,'source_core':'7dd5c14cdd88f3046f44613d22d346ef9d2fe833','target_core':owner['core'],'original_stores_opened':False,'carry_reset_required':False,'runtime_member':'PreserveRuntimeInstallation'})
receipt=save('preparation-receipt.json',{'state':'FROZEN READY: merged550/552,343/309/Text32 source, accepted installed lifetimes and changed filesystem witness; parent-only NEW publication','target_prefix':str(target),'source_prefix':str(source),'schema_equal':True,'native':owner['native'],'operator_manifest':str(base/'operator-manifest.json'),'operator_manifest_sha256':digest(base/'operator-manifest.json'),'source_proof_sha256':cohort.source_proof.sha256,'activation_sha256':cohort.activation.sha256,'runtime_sha256':digest(runtime),'public_effects':0,'old_failed337_operation_repeated':False,'new_publication_receipt':str(base/'publication-receipt.json'),'frontend_owner':'Lovelace accepted final309 return, source2809/mergedf415; no repeated Tree journey','bootstrap_deployment_owner':'Existing ActivateGlobalExtension/ReplaceGlobalSource, merged portable mode owner, pre-stop source digest/membership witness; source755 before atomic replacement'})
assert not (base/'publication-receipt.json').exists()
print(receipt.read_text())
