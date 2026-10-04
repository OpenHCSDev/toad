"""Freeze prepared original operands; do not execute the parent publisher."""
from pathlib import Path
import hashlib
import json
import shlex
import subprocess

out = Path(__file__).resolve().parent
base = out / 'new-publication436'
owner = json.loads((out / 'ownership.json').read_text())
proof = json.loads((out / 'source-proof.json').read_text())
cohort = json.loads((base / 'review-plan.json').read_text())
relation = json.loads((base / 'declaration-relation.json').read_text())
assert relation['whole_declared_native_schema_equal'] and not relation['runtime_carry_reset_required']
assert not (base / 'publication-receipt.json').exists()
assert not (base / 'publication-receipt.originals').exists()
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
protected = json.loads((out / 'protected-original433.json').read_text())
assert all(digest(Path(path)) == expected for path, expected in protected.items())
assert len(protected) == 274
assert sum(source['files'] for source in proof['sources']) == 942
operators = json.loads((base / 'operator-manifest.json').read_text())
assert len(operators) == 51
for item in operators:
    path = Path(item['path'])
    raw = subprocess.check_output(['git', '-C', '/home/ts/wt/comms-task-aware-native-bundle-20261002',
                                   'show', owner['core'] + ':tools/cutover/' + path.name])
    assert path.read_bytes() == raw and digest(path) == item['sha256']
for item in owner['archive_artifacts']:
    assert digest(Path(item['path'])) == item['sha256']
command = [str(Path(owner['prefix']) / 'bin/python'), '-I',
           str(base / 'operator-freeze/execute_retained_summary_foundation.py'),
           '--review-plan', str(base / 'review-plan.json'), '--receipt', str(base / 'publication-receipt.json'),
           '--runtime-installation', str(base / 'runtime-installation.json'), '--execute']
(base / 'execute-parent-command.txt').write_text(shlex.join(command) + '\n')
(base / 'readback-parent-command.txt').write_text(shlex.join([
    str(Path(owner['prefix']) / 'bin/python'), '-I', str(base / 'readback_publication.py')]) + '\n')
root_names = (
    'ownership.json', 'package-grant.json', 'protected-original433.json',
    'SOURCE-PLAN.json', 'core-wheel-source-receipt.json', 'core-wheel-relation.json',
    'requirements.txt', 'install.log', 'verify.py', 'verify-final.log', 'pipcheck-final.log',
    'source-proof.json', 'candidate-activation.json', 'native-artifact-receipt.json',
    'gate-originals.json', 'before-docs-merge-source-proof.json',
    'bind_docs_source_relation.py', 'prepare_candidate.py', 'candidate-preparation.log', 'freeze_ready.py',
)
paths = [out / name for name in root_names]
paths += list(out.glob('*-inventory.json'))
paths += [path for path in (out / 'qualified-source-gates').iterdir() if path.is_file()]
paths += [path for path in base.rglob('*') if path.is_file() and path.name != 'ready-receipt.json'
          and '__pycache__' not in path.parts and path.suffix != '.pyc']
paths = sorted(set(paths))
assert all(path.is_file() for path in paths)
ready = {
    'state': 'READY436 immutable granted style22 candidate; parent-only NEW original preserve publication',
    'source_head': owner['toad'], 'core': owner['core'], 'toad': owner['toad'],
    'textual': owner['textual'], 'audit': owner['audit'], 'native': owner['native'],
    'native_manifest': proof['native_manifest'], 'native_tree': proof['native_tree'],
    'target_prefix': owner['prefix'], 'source_prefix_derived_from_published_links': str(cohort['current_prefix']),
    'source_assets_equal': 942, 'native_forced_assets_equal': 3, 'package_count': 69, 'sdk': proof['sdk'],
    'canonical_operator_source': owner['core'], 'canonical_operator_members': 51,
    'full_cohort_require_original': 'PASS', 'native_schema_equal': True, 'derived_checkpoint_equal': True,
    'source_target_products_equal': False, 'runtime_member': 'PreserveRuntimeInstallation',
    'owner_member': 'PreserveOwnerRuntime', 'new_native_build': False,
    'core_builds': 1, 'toad_builds': 0, 'textual_builds': 0, 'new_vcs_clones': 0, 'environments_created': 0,
    'original_gate_count': len(owner['gate_files']), 'gate_files': owner['gate_files'],
    '637_scope': 'Original ordinary cold current-preview registered ACP/App16.280123s, actual Coordination/UserInput and four native segments; no unavailable-awareness emission claim',
    '430_Text59_scope': 'Original changed resource/lifetime App11.641s; no physical movie, smoothness, CPU or whole-performance claim',
    '417_scope': 'Accepted original reader13 App and recorded14 search/read/copy/export/exact-contributor scope; original current-awareness negative preserved and closed by independently accepted637; no repeated input/fork/provider',
    'earlier_qualification_scopes': 'Original F1 Start07/generalApp08/nativeDelete10, F4 savedApp06, 422 partial physical FALSE and Apps, 426 four Apps,429 startup App,Text53 mounted layers,Text58 reader lifetime retained at their actual scopes',
    'new_unchanged_gates_repeated': False,
    'preparation_negative': 'None in436; original433 preparation-negative and earliernative/SDK/UNKNOWN negatives preserved untouched',
    '638_640_633_scope': 'Original controlled-localhost SDK/application changed-family acceptance, sixteen then two/two corrected related cases. Original330/127/28 second-negative receipts retained; finaltwoPASS16.623s, allownednative/controller groups gone, external/public/replay0. No historicalspeed/model/publicdelivery claim.',
    'exclusions': ['627/W1', '432', 'JeV/private study product changes'],
    'source_proof_sha256': digest(out / 'source-proof.json'),
    'activation_sha256': digest(out / 'candidate-activation.json'),
    'review_plan_sha256': digest(base / 'review-plan.json'),
    'runtime_installation_sha256': digest(base / 'runtime-installation.json'),
    'operator_manifest_sha256': digest(base / 'operator-manifest.json'),
    'parent_execute_command_file': str(base / 'execute-parent-command.txt'),
    'readback_driver': str(base / 'readback_publication.py'),
    'publication_receipt_absent': True, 'preimages_absent': True, 'public_effects': 0,
    'protected_originals_files': 274, 'protected_original431_159_and433_114_ready_unchanged': True,
    'original_prefix_activation_unchanged': True, 'candidate_activation_is_own_output': True,
    'all_import_execution_commands_terminal': True,
    'artifacts': {str(path): digest(path) for path in paths},
}
(base / 'ready-receipt.json').write_text(json.dumps(ready, indent=2) + '\n')
print(json.dumps({'state': ready['state'], 'artifacts': len(paths), 'ready_sha256': digest(base / 'ready-receipt.json'),
                  'assets': 942, 'canonical_operators': 51, 'original_gates': len(owner['gate_files'])}))
