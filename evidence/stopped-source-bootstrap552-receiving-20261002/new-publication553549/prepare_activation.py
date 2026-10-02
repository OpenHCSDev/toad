from pathlib import Path
import json,sys
from agent_comms.field_codec import FieldCodec
from agent_comms.store_files import _atomic_write_text
sys.path.insert(0,'/home/ts/wt/comms-task-aware-native-bundle-20261002/tools/cutover')
from publish_retained_summary import CohortActivation,InstalledSourceProof
out=Path('/home/ts/wt/comms-task-aware-native-bundle-20261002/.artifacts/client-custody548-context547309-20261002')
proof=FieldCodec.decode(InstalledSourceProof,json.loads((out/'source-proof.json').read_text()))
activation=CohortActivation(
 stage=proof.prefix,
 pins={s.module:s.head for s in proof.sources if s.module!='textual_diff_view'},
 sdk=proof.sdk,textual_diff_view=next(s.head for s in proof.sources if s.module=='textual_diff_view'),
 native_package=proof.native_package,state='Normal69 merged549/553 canonical audience and native completion with550/552/343/309/Text32; accepted original gates preserved',
 staging_receipt=out/'source-proof.json',
 bins={name:str(proof.prefix/'bin'/name) for name in ('python','toad','agent-comms','agent-comms-acp','agent-comms-agent','pi-comms-native')},
 native_cli=proof.native_cli,native_manifest=proof.native_manifest,native_tree=proof.native_tree,
 native_configuration_note='Released old520 holder reused without new environment/native; actual547 prepared native configuration and original saved source; no provider/public changes; current334/333/frozen337 protected.',
)
proof.require_activation(activation)
original=(out/'new-publication548343'/'failed552-installed-source'/'activation.json').read_bytes()
assert (proof.prefix/'activation.json').read_bytes()==original, 'Released holder activation changed before matched replacement'
_atomic_write_text(proof.prefix/'activation.json',json.dumps(FieldCodec.encode(activation),indent=2)+'\n')
print(proof.prefix/'activation.json')
