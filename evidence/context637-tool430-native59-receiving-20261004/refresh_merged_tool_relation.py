"""Bind unchanged installed bytes to the accepted merged source identities."""
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import subprocess
import sys
from agent_comms.field_codec import FieldCodec

out = Path(__file__).resolve().parent
sys.path.insert(0, str(out / 'new-publication433/operator-freeze'))
from publish_retained_summary import InstalledSourceProof, CohortActivation
owner = json.loads((out / 'ownership.json').read_text())
proof = FieldCodec.decode(InstalledSourceProof, json.loads((out / 'before-merged643/source-proof.json').read_text()))
for module, repository, root in (
    ('agent_comms', '/home/ts/wt/comms-task-aware-native-bundle-20261002', 'src/agent_comms'),
    ('toad', '/home/ts/wt/toad-prompt-action-owner-20261002', 'src/toad'),
):
    before = next(source for source in proof.sources if source.module == module)
    after = owner['core' if module == 'agent_comms' else 'toad']
    subprocess.run(['git', '-C', repository, 'diff', '--exit-code', before.head, after, '--', root], check=True)
sources = tuple(replace(source, head=owner['core'] if source.module == 'agent_comms' else owner['toad'])
                if source.module in ('agent_comms', 'toad') else source for source in proof.sources)
final = replace(proof, sources=sources,
    state='Granted433 exact normal69 installed637/430/417/Text59; merged643 original-owner canonical tool and truthful source-equal identities; own candidate, original431 activation immutable')
activation = FieldCodec.decode(CohortActivation, json.loads((out / 'before-merged643/candidate-activation.json').read_text()))
activation = replace(activation, pins={source.module: source.head for source in sources if source.module != 'textual_diff_view'},
                     state=final.state)
final.require_activation(activation)
assert sum(source.files for source in sources) == 942
for path, expected in json.loads((out / 'protected-original431.json').read_text()).items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected, path
(out / 'source-proof.json').write_text(json.dumps(FieldCodec.encode(final), indent=2) + '\n')
(out / 'candidate-activation.json').write_text(json.dumps(FieldCodec.encode(activation), indent=2) + '\n')
print(json.dumps({'state': 'PASS unchanged installed package/source relation', 'core': owner['core'],
                  'toad': owner['toad'], 'assets': 942, 'package_restaged': False, 'original159_unchanged': True}))
