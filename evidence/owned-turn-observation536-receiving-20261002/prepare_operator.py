"""Prepare the reviewed Native6-preserving publisher; no public effects."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


WORKTREE = Path('/home/ts/wt/toad-prompt-action-owner-20261002')
ARTIFACTS = WORKTREE / '.artifacts/owned-turn-observation536-receiving-20261002'
TARGET = WORKTREE / '.artifacts/runtime-summary529-geometry322-20261002'
SOURCE = WORKTREE / '.artifacts/runtime-native-read532-534-retirement325-20261002'
EVIDENCE = WORKTREE / 'evidence/selected-publication530-sidebar323-receiving-20261002'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if sys.executable != str(TARGET / 'bin/python'):
        raise RuntimeError('Use the qualified target interpreter')
    manifest_path = ARTIFACTS / 'operator-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    operator = Path(manifest['operator_root'])
    for name, expected in manifest['files'].items():
        if digest(operator / name) != expected:
            raise RuntimeError(f'Frozen operator changed: {name}')
    sys.path.insert(0, str(operator))
    from agent_comms.active_route import read_active_route
    from agent_comms.field_codec import FieldCodec
    from native_schema_carry import NativeSchemaDeclaration
    from publish_retained_summary import ReviewedArtifact, ReviewedRetainedSummaryCohort
    from runtime_installation import PreserveRuntimeInstallation

    output = ARTIFACTS / 'operator-preparation'
    output.mkdir(mode=0o700)
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    original_data = json.loads(subprocess.check_output(
        [str(SOURCE / 'bin/python'), str(operator / 'native_schema_carry.py'), '--declaration'],
        env=environment, text=True))
    original = FieldCodec.decode(NativeSchemaDeclaration, original_data)
    target = NativeSchemaDeclaration.observe()
    if original != target or original.version != 6:
        raise RuntimeError('Source/target declarations differ; preserve-only plan refused')

    def artifact(path):
        return ReviewedArtifact(path, digest(path))

    cohort = ReviewedRetainedSummaryCohort(
        target=TARGET, source_interpreter=SOURCE / 'bin/python', current_prefix=SOURCE,
        original_route=read_active_route(), native=Path(json.loads((TARGET / 'activation.json').read_text())['native_package']),
        activation=artifact(TARGET / 'activation.json'), source_proof=artifact(ARTIFACTS / 'source-proof.json'),
        actual_gates=(artifact(ARTIFACTS / 'qualified-source-gates/536-DISPATCH-CONSUMPTION.md'),
                      artifact(ARTIFACTS / 'qualified-source-gates/536-READY.md')))
    cohort.require_original()
    runtime = PreserveRuntimeInstallation(goal_schema=original.goal)

    def save(name, value):
        path = output / name
        path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
        return path

    save('original-declaration.json', original_data)
    save('target-declaration.json', FieldCodec.encode(target))
    plan = save('review-plan.json', FieldCodec.encode(cohort))
    installation = save('runtime-installation.json', FieldCodec.encode(runtime))
    publication = output / 'publication-receipt.json'
    if publication.exists():
        raise RuntimeError('Original publication attempt exists; review required')
    command = [str(TARGET / 'bin/python'), str(operator / 'execute_retained_summary_foundation.py'),
               '--review-plan', str(plan), '--runtime-installation', str(installation),
               '--receipt', str(publication), '--execute']
    receipt = save('preparation-receipt.json', {
        'state': 'PREPARED, NOT EXECUTED', 'operator_manifest': str(manifest_path),
        'operator_manifest_sha256': digest(manifest_path), 'operator_members': manifest['members'],
        'operator_core': manifest['source_core'], 'target_core': manifest['target_core'], 'source_core': manifest['original_source'],
        'source_prefix': str(SOURCE), 'target_prefix': str(TARGET),
        'native_version': original.version, 'whole_declared_schema_equal': True,
        'runtime_member': type(runtime).__name__, 'historical_carry': False,
        'plan_sha256': digest(plan), 'runtime_installation_sha256': digest(installation),
        'source_proof_sha256': cohort.source_proof.sha256,
        'public_stops': 0, 'public_starts': 0, 'public_writes': 0,
        'owner_readiness_claim': False,
        'execution_condition': 'Parent reviewed execution only; existing publisher freshly recaptures/fences complete idle audience, no clients. Parent owns existing all-stopped preserve-only operation: recapture current complete configured audience, fresh idle/client check, one execution. Original536 six resource/child controls and final4changedhandler/cancellation1.26s qualification retained; frontend/native unchanged frompublished327. Fullsmooth/S1/S4 remain followups; configuredchannel acceptance parent-owned. No repeated provider/native journey.',
        'parent_execution_command': shlex.join(command)})
    print(receipt.read_text(), end='')


if __name__ == '__main__':
    main()
