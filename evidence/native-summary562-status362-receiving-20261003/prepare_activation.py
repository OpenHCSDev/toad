from pathlib import Path
import json,sys
from agent_comms.field_codec import FieldCodec
from agent_comms.store_files import _atomic_write_text
sys.path.insert(0,'/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/native-summary562-status362-receiving-20261003/new-publication562362/operator-freeze')
from publish_retained_summary import CohortActivation,InstalledSourceProof,ReviewedArtifact
out=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/native-summary562-status362-receiving-20261003')
proof=FieldCodec.decode(InstalledSourceProof,json.loads((out/'source-proof.json').read_text()))
activation=CohortActivation(
 stage=proof.prefix,
 pins={s.module:s.head for s in proof.sources if s.module!='textual_diff_view'},
 sdk=proof.sdk,textual_diff_view=next(s.head for s in proof.sources if s.module=='textual_diff_view'),
 native_package=proof.native_package,state='Normal69 merged560/562 plus Ready362 canonical status settlement owners; configured native044 preparation qualified',
 staging_receipt=out/'source-proof.json',
 bins={name:str(proof.prefix/'bin'/name) for name in ('python','toad','agent-comms','agent-comms-acp','agent-comms-agent','pi-comms-native')},
 native_cli=proof.native_cli,native_manifest=proof.native_manifest,native_tree=proof.native_tree,
 native_configuration_note=f'Released receiving holder {proof.prefix}; original activation/source/native and saved-source qualification proof archived. Public source, named rollback and other borrowed holders are untouched. Core/native and frontend follow this complete installed proof; no provider/public changes from packaging and no environment/native build.',
)
proof.require_activation(activation)
prepared=json.loads((out/'pre-final-preparation'/'preparation-receipt.json').read_text())
ReviewedArtifact(proof.prefix/'activation.json',prepared['activation_sha256']).require_original()
_atomic_write_text(proof.prefix/'activation.json',json.dumps(FieldCodec.encode(activation),indent=2)+'\n')
print(proof.prefix/'activation.json')
