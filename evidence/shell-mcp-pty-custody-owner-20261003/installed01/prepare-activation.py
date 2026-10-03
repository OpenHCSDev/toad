from pathlib import Path
import json,sys,hashlib
from agent_comms.field_codec import FieldCodec
from agent_comms.store_files import _atomic_write_text
sys.path.insert(0,'/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/settings-projection389-s4-relations584-receiving-20261003/new-publication583584585586384389/operator-freeze')
from publish_retained_summary import CohortActivation,InstalledSourceProof,ReviewedArtifact
out=Path(__file__).resolve().parent
proof=FieldCodec.decode(InstalledSourceProof,json.loads((out/'source-proof.json').read_text()))
original=out/'before-activation.json'
activation_path=proof.prefix/'activation.json'
ReviewedArtifact(activation_path,hashlib.sha256(original.read_bytes()).hexdigest()).require_original()
activation=CohortActivation(stage=proof.prefix,pins={s.module:s.head for s in proof.sources if s.module!='textual_diff_view'},sdk=proof.sdk,textual_diff_view=next(s.head for s in proof.sources if s.module=='textual_diff_view'),native_package=proof.native_package,state='Private392 matched CoreCTTY/Toad source; shell and MCP actual AppPTY checks pending',staging_receipt=out/'source-proof.json',bins={name:str(proof.prefix/'bin'/name) for name in ('python','toad','agent-comms','agent-comms-acp','agent-comms-agent','pi-comms-native')},native_cli=proof.native_cli,native_manifest=proof.native_manifest,native_tree=proof.native_tree,native_configuration_note='Sch explicit style22 release after588App05; original391/588 archives retained. NormalCore590/Toad392 wheel refresh in same69 environment; native2b unchanged, no provider/public/default changes.')
proof.require_activation(activation)
_atomic_write_text(activation_path,json.dumps(FieldCodec.encode(activation),indent=2)+'\n')
print(activation_path)
