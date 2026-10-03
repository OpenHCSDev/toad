"""One-use reviewed index member; original publisher owns stop/install/launch."""
from pathlib import Path
import argparse
import json
import sys
base=Path(__file__).resolve().parent
operator=base/'operator-freeze'
sys.path.insert(0,str(operator))
from agent_comms.field_codec import FieldCodec
from publish_retained_summary import ReviewedArtifact,ReviewedRetainedSummaryCohort,publish
from retained_index_cutover import RetainedIndexCutover
from runtime_installation import RuntimeInstallation

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--execute',action='store_true')
 args=parser.parse_args()
 if not args.execute:parser.error('Parent-only reviewed one-use publication requires --execute')
 ready=json.loads((base/'ready-receipt.json').read_text())
 for path,sha in ready['execution_artifacts'].items():ReviewedArtifact(Path(path),sha).require_original()
 manifest=json.loads((base/'operator-manifest.json').read_text())
 for name,sha in manifest['files'].items():ReviewedArtifact(operator/name,sha).require_original()
 cohort=FieldCodec.decode(ReviewedRetainedSummaryCohort,json.loads((base/'review-plan.json').read_text()))
 runtime=FieldCodec.decode(RuntimeInstallation,json.loads((base/'runtime-installation.json').read_text()))
 member=RetainedIndexCutover(cohort.source_interpreter,cohort.original_route.wire_root_id,cohort.native)
 results=publish(cohort,member,runtime,base/'publication-receipt.json')
 print(json.dumps({'state':'retained-index-published-and-launched','owners':len(results)}),flush=True)
if __name__=='__main__':main()
