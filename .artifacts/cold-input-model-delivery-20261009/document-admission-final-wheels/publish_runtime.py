from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,'/home/ts/wt/comms-goal-ledger-schema-carry-20261002/tools/cutover')
from publish_retained_summary import ReviewedPairedRuntimeCohort,ReviewedArtifact
from agent_comms.active_route import read_active_route
root=Path(__file__).parent
out=root.parent
target=out/'publication-release-runtime'
result=json.loads((root/'actual-application-result.json').read_text())
assert result['original_app_joined'] and result['original_app_exit_code']==0 and result['original_worker_stopped']
assert all(not Path('/proc',str(row['pid'])).exists() for row in result['processes'])
assert sys.executable==str(target/'bin/python')
def artifact(path):
    return ReviewedArtifact(path,hashlib.sha256(path.read_bytes()).hexdigest())
route=read_active_route()
cohort=ReviewedPairedRuntimeCohort(target=target,current_prefix=out/'current-ui-runtime',frontend_prefix=out/'current-ui-runtime',original_route=route,native=route.native_package,activation=artifact(root/'candidate-activation.json'),source_proof=artifact(root/'source-proof.json'),actual_gates=(artifact(root/'actual-application-result.json'),))
cohort.publish_defaults(root/'live-publication.json')
print('Published the reviewed same-format runtime for future launches. Existing owners and native supply retained; scroll performance remains unfinished.')
