from pathlib import Path
from dataclasses import replace
import json,sys,subprocess
from agent_comms.field_codec import FieldCodec
out=Path(__file__).resolve().parent
sys.path.insert(0,str(out/'operator-freeze'))
from publish_retained_summary import InstalledSourceProof
proof=FieldCodec.decode(InstalledSourceProof,json.loads((out/'source-proof.json').read_text()))
owner=json.loads((out/'ownership.json').read_text())
source=next(s for s in proof.sources if s.module=='toad')
subprocess.run(['git','diff','--exit-code',source.head,owner['toad'],'--','src/toad'],check=True)
proof=replace(proof,sources=tuple(replace(s,head=owner['toad']) if s.module=='toad' else s for s in proof.sources))
(out/'source-proof.json').write_text(json.dumps(FieldCodec.encode(proof),indent=2)+'\n')
print('Normal docs-main source relation PASS; no package restage')
