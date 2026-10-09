import hashlib
import importlib
import importlib.metadata as metadata
import json
import sys
import zipfile
import tomllib
from dataclasses import replace
from pathlib import Path

OUT = Path(__file__).parent
BASE = Path('/home/ts/wt/comms-goal-ledger-schema-carry-20261002/.artifacts/cold-input-config-admission-20261008/deployment/current-core-bc1f3a81')
PREFIX = Path('/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/current-ui-runtime')
assert Path(sys.prefix) == PREFIX
sys.path.insert(0, '/home/ts/wt/comms-goal-ledger-schema-carry-20261002/tools/cutover')
from publish_retained_summary import InstalledSource, InstalledSourceProof, CohortActivation
from agent_comms.field_codec import FieldCodec

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(name, value):
    with (OUT / name).open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')

original = json.loads((BASE / 'source-proof.json').read_text())
raw = dict(original)
raw.update(prefix=str(PREFIX), state='Reviewed same-format paired successor; App pending',
           public_install_changed=False,
           journey_assessment='Affected installed successor check pending')
changed = {'toad': ('45596c8b460842ec2d77830122bc7418db1392f0', Path('/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/document-control-wheels/batrachian_toad-0.6.20-py3-none-any.whl'), Path('/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/document-control-wheels/toad-source/src/toad')), 'textual': ('09004210cdd5dff4bb4050b370fdbe2bda6c710c', Path('/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/document-control-wheels/textual-8.2.8-py3-none-any.whl'), Path('/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/document-control-wheels/textual-source/src/textual')), 'agent_comms': ('1a45e9b552dcc6890f7eb090a73cb1f9a617f2a7', Path('/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/document-control-wheels/agent_comms-0.1.0-py3-none-any.whl'), Path('/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/document-control-wheels/core-source/src/agent_comms'))}

sources = []
artifacts = []
for before in original['sources']:
    name = before['module']
    location = Path(importlib.import_module(name).__file__).parent
    assert location.is_relative_to(PREFIX)
    owner = replace(FieldCodec.decode(InstalledSource, before), location=str(location))
    direct = json.loads(owner.distribution().read_text('direct_url.json'))
    if name in changed:
        head, wheel, git_source = changed[name]
        assert direct['url'] == wheel.as_uri()
    else:
        assert direct == before['direct_url']
        head = before['head']
        wheel = next(Path(row['path']) for row in original['archive_artifacts']
                     if row['path'] == direct['url'].removeprefix('file://'))
        git_source = None
    assets = []
    forced = {}
    if git_source is not None:
        project = git_source.parents[1]
        declaration = tomllib.loads((project / 'pyproject.toml').read_text())
        forced = {target: project / origin for origin, target in
                  declaration.get('tool', {}).get('hatch', {}).get('build', {}).get('targets', {}).get('wheel', {}).get('force-include', {}).items()}
    with zipfile.ZipFile(wheel) as archive:
        members = sorted(member for member in archive.namelist()
                         if member.startswith(name + '/') and not member.endswith('/'))
        for member in members:
            body = archive.read(member)
            assert (location.parent / member).read_bytes() == body, member
            if git_source is not None:
                declared_source = forced.get(member, git_source / Path(member).relative_to(name))
                assert declared_source.read_bytes() == body, member
            assets.append({'member': member, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)})
    actual = {str(path.relative_to(location.parent)) for path in location.rglob('*')
              if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}
    assert actual == set(members)
    if git_source is None:
        assert len(assets) == before['files']
    else:
        expected = {str(path.relative_to(git_source.parent)) for path in git_source.rglob('*')
                    if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}
        expected.update(forced)
        assert set(members) == expected, (name, set(members) ^ expected)
    write(name + '-installed-inventory.json', {'module': name, 'assets': assets, 'byte_equal': True, 'missing_extra': []})
    source = dict(before)
    source.update(head=head, location=str(location), direct_url=direct, files=len(assets),
                  python_files=sum(row['member'].endswith('.py') for row in assets),
                  inventory_sha256=digest(OUT / (name + '-installed-inventory.json')))
    sources.append(source)
    artifacts.append({'path': str(wheel), 'sha256': digest(wheel)})
asset_count = sum(source['files'] for source in sources)
packages = sorted((distribution.metadata['Name'], distribution.version)
                  for distribution in metadata.distributions())
assert [list(pair) for pair in packages] == original['packages']
assert len(packages) == 69
raw.update(sources=sources, archive_artifacts=artifacts, requirements_sha256=digest(OUT / 'requirements.txt'))
activation = json.loads((BASE / 'candidate-activation.json').read_text())
activation.update(stage=str(PREFIX), pins={source['module']: source['head'] for source in sources
                                         if source['module'] != 'textual_diff_view'},
                  state='Reviewed same-format paired successor', staging_receipt=str(OUT / 'source-proof.json'),
                  bins={name: str(PREFIX / 'bin' / name) for name in activation['bins']})
proof = FieldCodec.decode(InstalledSourceProof, raw)
dto = FieldCodec.decode(CohortActivation, activation)
proof.require_activation(dto)
write('source-proof.json', FieldCodec.encode(proof))
write('candidate-activation.json', FieldCodec.encode(dto))
print(json.dumps({'assets': asset_count, 'packages': 69, 'sources': [(row['module'], row['head']) for row in sources]}))
