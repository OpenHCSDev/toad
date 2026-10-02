from pathlib import Path
from dataclasses import replace
import hashlib,json,sys
wt=Path('/home/ts/wt/toad-prompt-action-owner-20261002')
out=wt/'.artifacts/summary529-geometry322-20261002'
prefix=wt/'.artifacts/runtime-summary529-geometry322-20261002'
prep=out/'operator-preparation'
def read(p): return json.loads(p.read_text())
def write(p,v): p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert not (prep/'publication-receipt.json').exists()
owner=read(out/'ownership.json'); owner.update(receiving_pr=324,gate_owner='Original322 physical geometry and529 configured saved-source/native qualifications; parent default final gate',original_prefix=str(wt/'.artifacts/runtime-progress528-source-resource525-20261002'))
write(out/'ownership.json',owner)
journey_owners=['Heisenberg original322 physical geometry107s; product source equal', 'Arendt original529 configured saved-native compaction162s with distinct input/reply; qualified761 production equal merged d6', 'Parent preserve-only publication and ordinary default final verification']
v=out/'verify.py'; text=v.read_text(); old="['Parent default read; unchanged Core877/native5184, original322107s source qualification retained']"; assert old in text; v.write_text(text.replace(old,repr(journey_owners)))
p=out/'source-proof.json'; original=p.read_bytes(); (out/'source-proof-before-description-correction.json').write_bytes(original)
proof=read(p); proof['journey_owners']=journey_owners; write(p,proof)
sys.path.insert(0,str(out/'operator-freeze'))
from agent_comms.field_codec import FieldCodec
from publish_retained_summary import ReviewedRetainedSummaryCohort,ReviewedArtifact
planpath=prep/'review-plan.json'
cohort=FieldCodec.decode(ReviewedRetainedSummaryCohort,read(planpath))
cohort=replace(cohort,source_proof=ReviewedArtifact(p,digest(p)))
cohort.require_original()
write(planpath,FieldCodec.encode(cohort))
receipt=read(prep/'preparation-receipt.json'); receipt.update(plan_sha256=digest(planpath),source_proof_sha256=digest(p)); write(prep/'preparation-receipt.json',receipt)
write(out/'metadata-correction.json',{'scope':'Unpublished metadata descriptions only; package/source/native/protected-file checks retained unchanged', 'previous_source_proof_sha256':hashlib.sha256(original).hexdigest(),'final_source_proof_sha256':digest(p),'updated_fields':['ownership.receiving_pr','ownership.gate_owner','ownership.original_prefix','source_proof.journey_owners','review_plan.source_proof.sha256','preparation.plan_sha256','preparation.source_proof_sha256'],'package_bytes_changed':False,'publication_executed':False})
ready={ 'state':'READY for parent preserve-only publication; NOT EXECUTED','prefix':str(prefix),'python':str(prefix/'bin/python'),'core':owner['core'],'toad':owner['toad'],'textual':owner['textual'],'sdk':proof['sdk'],'package_count':proof['package_count'],'native_package':proof['native_package'],'native_manifest':proof['native_manifest'],'native_tree':proof['native_tree'],'native_full_trust':True,'source_proof_sha256':digest(p),'activation_sha256':digest(prefix/'activation.json'),'operator_manifest_sha256':digest(out/'operator-manifest.json'),'review_plan_sha256':digest(planpath),'runtime_installation_sha256':digest(prep/'runtime-installation.json'),'whole_native_schema_equal':True,'native_schema_version':6,'historical_carry':False,'format_reset':False,'existing_current_previous_files_unchanged':proof['protected_old_prefix_files'],'source_equality':read(out/'qualified-source-equality.json'),'actual_gates':[{ 'path':str(x.path),'sha256':x.sha256} for x in cohort.actual_gates],'qualification_scope':'322/Text25 physical geometry and body-capture lifetime (107s; partial mixed performance) plus529 configured42MB native manual compaction with peer/new distinct input/reply (162s). No full smoothness/CPU or S1/S4 claim. Existing530 peer/preflight negative remains separate. Parent ordinary default final verification pending.','new_native_build':False,'new_provider_input':False,'new_capture':False,'source_overlay':False,'public_writes':0,'public_stops':0,'public_starts':0,'publication_owner':'Parent: existing ALL-STOPPED PublishRetainedSummary + PreserveRuntimeInstallation + PreserveOwnerRuntime; freshly admit complete original idle/client-free audience. No independent UI-only writer.','parent_execution_command':receipt['parent_execution_command'],'supersedes_standalone324_publication':True}
write(out/'ready-receipt.json',ready)
print(json.dumps({'source_proof_sha256':digest(p),'activation_sha256':ready['activation_sha256'],'ready_receipt_sha256':digest(out/'ready-receipt.json'),'operator_manifest_sha256':ready['operator_manifest_sha256'],'parent_execution_command':receipt['parent_execution_command']},indent=2))
