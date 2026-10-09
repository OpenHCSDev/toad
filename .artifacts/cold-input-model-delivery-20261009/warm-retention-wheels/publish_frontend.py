from pathlib import Path
import sys, json, hashlib
sys.path.insert(0, '/home/ts/wt/comms-goal-ledger-schema-carry-20261002/tools/cutover')
from publish_retained_summary import ReviewedTextualFrontendCohort, ReviewedArtifact
from agent_comms.active_route import read_active_route
from agent_comms.field_codec import FieldCodec
root = Path(__file__).parent
current = root.parent / 'runtime'
target = root.parent / 'body-diagnostic-runtime'
backend = Path('/home/ts/wt/comms-goal-ledger-schema-carry-20261002/.artifacts/cold-input-config-admission-20261008/deployment/current-core-bc1f3a81/source-proof.json')
def artifact(path):
    return ReviewedArtifact(path, hashlib.sha256(path.read_bytes()).hexdigest())
result = json.loads((root / 'actual-application-result.json').read_text())
assert result['original_app_joined'] and result['original_app_exit_code'] == 0 and result['original_worker_stopped']
assert all(not (Path('/proc') / str(row['pid'])).exists() for row in result['processes'])
assert sys.executable == str(target / 'bin/python')
assert Path('/home/ts/.local/bin/toad').readlink() == current / 'bin/toad'
cohort = ReviewedTextualFrontendCohort(
    target=target, current_prefix=current, original_route=read_active_route(),
    native=read_active_route().native_package,
    activation=artifact(root / 'candidate-activation.json'),
    source_proof=artifact(root / 'source-proof.json'),
    actual_gates=(artifact(root / 'actual-application-result.json'),),
    current_source_proof=artifact(backend), backend_source_proof=artifact(backend),
)
cohort.publish_defaults(root / 'live-publication.json')
print('Published history retention and renderer progress for new Toad launches. Existing backend owners and native route preserved; frame target remains unmet.')
