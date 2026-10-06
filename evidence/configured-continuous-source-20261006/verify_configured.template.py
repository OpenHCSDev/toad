"""UNISSUED configured reader-pair installed source/FullTrust proof; do not execute."""
import hashlib
import importlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

OUT = Path(__file__).parent
GRANT = Path("UNBOUND_CONFIGURED_ACTUAL_ISSUED_GRANT_PATH")

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')

assert digest(GRANT) == 'UNBOUND_CONFIGURED_ACTUAL_ISSUED_GRANT_SHA256'
grant = json.loads(GRANT.read_text())
lifecycle = json.loads(Path(grant['lifecycle']).read_text())
assert lifecycle['proof_execution_authorized'] and lifecycle['native_READ_authorized']
assert not lifecycle['native_EXEC_authorized'] and not lifecycle['execution_authorized']
authority = Path('UNBOUND_CONFIGURED_ACTUAL_NATIVE_READ_PATH')
assert digest(authority) == 'UNBOUND_CONFIGURED_ACTUAL_NATIVE_READ_SHA256'
assert OUT == Path(grant['owned_output'])
assert lifecycle['proof_argv'] == [str(Path(grant['prefix'])/'bin/python'), '-B', str(Path(__file__).resolve())]
assert lifecycle['proof_helper']['sha256'] == digest(__file__)
assert lifecycle['issued_sha256'] == digest(GRANT)
read_authority = json.loads(authority.read_text())
assert read_authority['holder_grant']['sha256'] == digest(GRANT)
assert read_authority['native_READ_authorized'] and not read_authority['native_EXEC_authorized']
destinations = [OUT / (name + '-installed-inventory.json') for name in ('agent_comms', 'toad', 'textual', 'textual_diff_view', 'refactor_audit')]
destinations += [OUT / name for name in ('native-full-trust.json', 'source-proof.json', 'candidate-activation.json', 'package-boundary-proof.json')]
assert all(not path.exists() and not path.is_symlink() for path in destinations)
prefix = Path(grant['prefix'])
assert Path(sys.prefix) == prefix and not os.environ.get('PYTHONPATH') and not os.environ.get('PYTHONHOME')
for record in grant['unchanged_other66_unique_records']:
    path = Path(record['path'])
    assert stat.S_IMODE(path.lstat().st_mode) == record['mode'], path
    if record['kind'] == 'symlink':
        assert os.readlink(path) == record['target'], path
    else:
        assert digest(path) == record['sha256'], path
for name, expected in grant['protected_originals'].items():
    path = Path(name)
    assert digest(path) == expected['sha256'] and stat.S_IMODE(path.stat().st_mode) == expected['mode'], path
for control in grant['controls_and_helpers']:
    assert digest(control['path']) == control['sha256'], control['path']

packages = {d.metadata['Name']: d.version for d in metadata.distributions()}
expected = dict(grant['normal_distributions'])
assert packages == expected and len(packages) == 69, (packages, expected)
for name, original in grant['original69_origins'].items():
    if name in ('agent-comms', 'batrachian-toad', 'textual'):
        continue
    raw = metadata.distribution(name).read_text('direct_url.json')
    assert (None if raw is None else json.loads(raw)) == (None if original is None else original['contents']), name

inputs = [(row['module'], row['distribution'], row['head'], Path(row['path']), row['sha256'])
          for row in grant['source_filewheels']]
diff = next(row for row in grant['source_filewheels'] if row['module'] == 'textual_diff_view')
sources, artifacts, inventories = [], [], {}
for module_name, distribution, head, wheel, wheel_sha in inputs:
    assert digest(wheel) == wheel_sha
    module = importlib.import_module(module_name)
    location = Path(module.__file__).parent
    assert location.is_relative_to(prefix), location
    with zipfile.ZipFile(wheel) as archive:
        members = sorted(n for n in archive.namelist() if n.startswith(module_name + '/') and not n.endswith('/'))
        inventory = []
        for member in members:
            raw = archive.read(member)
            sha = hashlib.sha256(raw).hexdigest()
            assert digest(location.parent/member) == sha, member
            inventory.append({'member':member, 'sha256':sha, 'bytes':len(raw)})
    actual = {str(p.relative_to(location.parent)) for p in location.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    assert actual == set(members), (module_name, actual.symmetric_difference(members))
    inventory_path = OUT/(module_name+'-installed-inventory.json')
    write(inventory_path, {'module':module_name, 'wheel':str(wheel), 'wheel_sha256':wheel_sha, 'assets':inventory, 'byte_equal':True, 'missing_extra':[]})
    direct_url = json.loads(metadata.distribution(distribution).read_text('direct_url.json'))
    if module_name not in ('agent_comms', 'toad', 'textual'):
        assert direct_url == grant['original69_origins'][distribution]['contents']
    else:
        assert direct_url['url'] == wheel.as_uri(), direct_url
    sources.append({'module':module_name, 'head':head, 'location':str(location), 'files':len(members), 'python_files':sum(n.endswith('.py') for n in members), 'byte_equal':True, 'direct_url':direct_url, 'inventory_sha256':digest(inventory_path)})
    artifacts.append({'path':str(wheel), 'sha256':wheel_sha})
    inventories[module_name]={'path':str(inventory_path), 'sha256':digest(inventory_path)}
assert sum(s['files'] for s in sources) == 953
assert digest(prefix/'lib/python3.14/site-packages/refactor_audit/measures.py') == '8f6127cb184801fbf2ca162adbece5c103c0fc6693f81197632668f710af7513'

sys.path.insert(0, '/home/ts/wt/comms-configured-continuous-producer-20261006/tools/cutover')
from publish_retained_summary import CohortActivation, InstalledSourceProof
from agent_comms.field_codec import FieldCodec
from agent_comms.native_package import verify_native_package, package_tree_digest, MANIFEST
native=grant['matching_native_reference'];native_path=Path(native['package'])
assert digest(MANIFEST)==native['manifest']
verify_native_package(native_path)
assert package_tree_digest(native_path)==native['tree']
write(OUT/'native-full-trust.json', {'authority':str(authority), 'authority_sha256':digest(authority), 'package':str(native_path), 'manifest':native['manifest'], 'tree':native['tree'], 'native_full_trust':True, 'artifact_execution':False, 'artifact_writes':False})
package_tuple=[list(pair) for pair in sorted(packages.items())]
for record in grant['original_environment_bootstrap_records']:
    path=Path(record['path'])
    assert digest(path)==record['sha256'] and stat.S_IMODE(path.stat().st_mode)==record['mode'], path
prefix_activation=grant['actual_PREFIXactivation']
assert digest(Path(prefix_activation['path']))==prefix_activation['sha256']
requirements_sha=hashlib.sha256(json.dumps(package_tuple,separators=(',',':')).encode()).hexdigest()
sdk=metadata.version('agent-client-protocol');assert sdk=='0.12.1'
proof_raw={'state':'HELD configured repaired pair installed source/immutable READ proof; App unrun', 'prefix':str(prefix), 'sources':sources, 'native_package':str(native_path), 'native_cli':str(native_path/'dist/cli.js'), 'native_manifest':native['manifest'], 'native_tree':native['tree'], 'native_full_trust':True, 'sdk':sdk, 'package_count':len(packages), 'packages':package_tuple, 'requirements_sha256':requirements_sha, 'protected_old_prefix_files':266, 'protected_old_prefix_files_unchanged':True, 'public_install_changed':False, 'new_native_build':False, 'source_overlay':False, 'dependency_bypass':False, 'journey_owners':['Original Heis configured saved continuous journey only after fresh source READ, matching private4b EXEC and Bohr release; six authored UI inputs plus native automatic handling'], 'journey_assessment':'953 original packaged assets, full69 versions and truthful origins;1883other66+266keepers/bootstrap2/PREFIX unchanged. Coreddcdc6b426, repaired Toad afae410c and Text71bc47 staged normally. No App/render controller/nativeSDK/ACP/provider/input executed.', 'archive_artifacts':artifacts}
activation_raw={'stage':str(prefix), 'pins':{s['module']:s['head'] for s in sources if s['module']!='textual_diff_view'}, 'sdk':sdk, 'textual_diff_view':diff['head'], 'native_package':str(native_path), 'state':'HELD configured repaired pair actualNONLIVE former485 CURRENT471 purpose; App unrun', 'staging_receipt':str(OUT/'source-proof.json'), 'bins':{name:str(prefix/'bin'/name) for name in ('python','toad','agent-comms','agent-comms-acp','agent-comms-agent','pi-comms-native')}, 'native_cli':str(native_path/'dist/cli.js'), 'native_manifest':native['manifest'], 'native_tree':native['tree'], 'native_configuration_note':'Actual NONLIVE former485 CURRENT471 fresh1467 preimage authoritative; historical1563 archive is CURRENT459 only. Full69 original origins,266 protected/bootstrap2/PREFIX+1883 other66 unchanged. Three normal candidates Coreddcdc6b426, repaired Toadafae410c and nativeText71bc47. Candidate953 original source assets. Future configured journey has six authored UI inputs plus native automatic handling; original PUBLIC475 source read only at actual released acquisition. Actual CURRENT471 Core3fe+Toadb2e+Text16c9 normal restore after terminal. NEW matching4b READ for proof only; App HELD separate newEXEC and Bohr release.'}
proof=FieldCodec.decode(InstalledSourceProof,proof_raw);activation=FieldCodec.decode(CohortActivation,activation_raw)
proof.require_activation(activation)
for source in proof.sources:
    source.require_package(source.module,Path(source.location),next(s['direct_url'] for s in sources if s['module']==source.module),proof.archive_artifacts)
write(OUT/'source-proof.json',FieldCodec.encode(proof));write(OUT/'candidate-activation.json',FieldCodec.encode(activation))
write(OUT/'package-boundary-proof.json',{'issued_sha256':digest(GRANT), 'source_assets':953, 'source_inventories':inventories, 'package_count':69, 'other66_unchanged':1883, 'protected_originals_unchanged':266, 'sdk':sdk, 'native_full_trust':True, 'Apps_run':0, 'renderer_controls_run':0})
print(json.dumps({'state':'PROOF PASS controls HELD', 'sources':[(r['module'],r['files']) for r in sources], 'proof_sha256':digest(OUT/'source-proof.json'), 'DTO_sha256':digest(OUT/'candidate-activation.json'), 'boundary_sha256':digest(OUT/'package-boundary-proof.json'), 'native_trust_sha256':digest(OUT/'native-full-trust.json')}))
