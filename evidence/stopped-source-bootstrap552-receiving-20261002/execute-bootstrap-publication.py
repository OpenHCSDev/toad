"""One-use reviewed operands; the existing publisher owns all lifecycle work."""
from pathlib import Path
import argparse
import json
import sys

base = Path(__file__).resolve().parent
operator = base / 'operator-final552'
sys.path.insert(0, str(operator))
from agent_comms.field_codec import FieldCodec
from global_extension_activation import ActivateGlobalExtension, ReplaceGlobalSource
from publish_retained_summary import ReviewedArtifact, ReviewedRetainedSummaryCohort, publish
from runtime_installation import RuntimeInstallation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        parser.error('This is the reviewed parent-only one-use publication command')
    ready = json.loads((base / 'ready-receipt.json').read_text())
    for path, sha256 in ready['execution_artifacts'].items():
        ReviewedArtifact(Path(path), sha256).require_original()
    manifest = json.loads((base / 'operator-manifest.json').read_text())
    for name, sha256 in manifest['files'].items():
        ReviewedArtifact(operator / name, sha256).require_original()
    cohort = FieldCodec.decode(ReviewedRetainedSummaryCohort,
                              json.loads((base / 'review-plan.json').read_text()))
    runtime = FieldCodec.decode(RuntimeInstallation,
                               json.loads((base / 'runtime-installation.json').read_text()))
    source, original = FieldCodec.decode(tuple[ReviewedArtifact, ReviewedArtifact],
                                       json.loads((base / 'source-installation.json').read_text()))
    member = ActivateGlobalExtension(
        (ReplaceGlobalSource(source, original.path, original),),
        base / 'bootstrap-preimages')
    results = publish(cohort, member, runtime, base / 'publication-receipt.json')
    print(json.dumps({'state': 'retained-foundation-published-and-launched',
                      'owners': len(results)}), flush=True)


if __name__ == '__main__':
    main()
