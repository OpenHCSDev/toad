"""One issued 466 source/READ proof using the original typed receipt owners."""
import base64,csv,hashlib,importlib,importlib.metadata as metadata,io,json,os,stat,sys,zipfile
from dataclasses import replace
from pathlib import Path
GRANT,grant_sha,AUTHORITY,authority_sha,OUTPUT=sys.argv[1:]
GRANT,AUTHORITY,OUT=Path(GRANT),Path(AUTHORITY),Path(OUTPUT)
def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
def write(name,value):
    with (OUT/name).open('x') as stream:
        stream.write(json.dumps(value,indent=2)+'\n')
def original(record):
    path=Path(record['path'])
    assert stat.S_IMODE(path.lstat().st_mode)==record['mode'],path
    if record['kind']=='symlink':
        assert os.readlink(path)==record['target'],path
    else:
        assert digest(path)==record['sha256'],path
assert digest(GRANT)==grant_sha
g=json.loads(GRANT.read_text());lp=Path(g['lifecycle']);l=json.loads(lp.read_text())
assert l['proof_execution_authorized'] and l['native_READ_authorized']
assert not l['execution_authorized'] and not l['native_EXEC_authorized']
assert digest(AUTHORITY)==authority_sha
read=json.loads(AUTHORITY.read_text())
assert read['holder_grant']=={'path':str(GRANT),'sha256':grant_sha}
assert read['native_READ_authorized'] and not read['native_EXEC_authorized']
assert OUT==Path(g['owned_output'])
prefix=Path(g['prefix']);assert Path(sys.prefix)==prefix
assert not os.environ.get('PYTHONPATH') and not os.environ.get('PYTHONHOME')
site=prefix/'lib/python3.14/site-packages'
for record in g['unchanged_other65_records']:
    original(record)
for record in g['original_records']:
    path=Path(record['path'])
    if path.is_relative_to(site/'toad') or path.is_relative_to(site/'batrachian_toad-0.6.20.dist-info'):
        continue
    original(record)
for path,record in g['protected_originals'].items():
    assert digest(path)==record['sha256'],path
    assert stat.S_IMODE(Path(path).stat().st_mode)==record['mode'],path
assert digest(g['actual_PREFIXactivation']['path'])==g['actual_PREFIXactivation']['sha256']
for key in ('exact_control','exact_helper'):
    assert digest(g[key]['path'])==g[key]['sha256']
packages={d.metadata['Name']:d.version for d in metadata.distributions()}
assert packages==g['normal_distributions'] and len(packages)==69
origins={}
for name,prior in g['original69_origins'].items():
    text=metadata.distribution(name).read_text('direct_url.json')
    origins[name]=None if text is None else json.loads(text)
    if name!='batrachian-toad':
        assert origins[name]==(None if prior is None else prior['contents']),name
# Import only the byte-qualified original tool owner; application paths stay installed.
owner=Path('/home/ts/wt/comms-field-codec-closure-20260928/tools/cutover/publish_retained_summary.py')
assert digest(owner)=='025babf120563228d99920617d34f2e4142307d38e049405d4af49b2ecd7a960'
sys.path.append(str(owner.parent))
from publish_retained_summary import CohortActivation,InstalledSourceProof,InstalledSource,ReviewedArtifact
from agent_comms.field_codec import FieldCodec
from agent_comms.native_package import verify_native_package,package_tree_digest,MANIFEST
prior_path=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/merged457-goal675-native67-receiving-20261005/source-proof.json')
assert digest(prior_path)=='f07c68f783974b1a2312ebd5650131aab3dbb79e48ef9c58a1707426d47c8e29'
prior=FieldCodec.decode(InstalledSourceProof,json.loads(prior_path.read_text()))
heads={**g['current_source_heads'],'toad':g['wheel_build_head']}
inputs=[('agent_comms','agent-comms',g['current_source_filewheels'][0]),('toad','batrachian-toad',g['candidate_wheel']),('textual','textual',g['current_source_filewheels'][2]),('refactor_audit','nominal-refactor-audit',g['current_source_filewheels'][3]),('textual_diff_view','textual-diff-view',{'path':'/home/ts/.cache/uv/sdists-v9/git/6a8a377ce2150d3f/8fa7d4d0db993ea3/textual_diff_view-0.1.5-py3-none-any.whl','sha256':'be7089c8f282e07e893b0254a0859e0f1b243a7ba591749f2053fa1fb775ad36'})]
sources=[];artifacts=[];inventories={};buildmetadata={}
for module_name,distname,wheel_record in inputs:
    wheel=Path(wheel_record['path']);assert digest(wheel)==wheel_record['sha256']
    module=importlib.import_module(module_name);location=Path(module.__file__).parent
    assert location.parent==site,location
    with zipfile.ZipFile(wheel) as archive:
        members=sorted(n for n in archive.namelist() if n.startswith(module_name+'/') and not n.endswith('/'))
        assets=[]
        for member in members:
            raw=archive.read(member);sha=hashlib.sha256(raw).hexdigest()
            assert digest(site/member)==sha,member
            assets.append({'member':member,'bytes':len(raw),'sha256':sha})
        actual={str(p.relative_to(site)) for p in location.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        assert actual==set(members),(module_name,actual.symmetric_difference(members))
        record=next(n for n in archive.namelist() if n.endswith('.dist-info/RECORD'))
        entries=list(csv.reader(io.StringIO(archive.read(record).decode())))
        assert {entry[0] for entry in entries}==set(archive.namelist())
        meta={}
        for name,encoded,size in entries:
            raw=archive.read(name)
            if encoded:
                algorithm,hash_=encoded.split('=',1)
                assert base64.urlsafe_b64encode(hashlib.new(algorithm,raw).digest()).rstrip(b'=').decode()==hash_
                assert len(raw)==int(size)
            else:
                assert name==record and not size
            if '.dist-info/' in name and name!=record:
                assert (site/name).read_bytes()==raw,name
                meta[name]=hashlib.sha256(raw).hexdigest()
        buildmetadata[module_name]={'RECORD_entries':len(entries),'installed_metadata_byte_equal':True,'dist_info_sha256':meta}
    inventory_path=OUT/(module_name+'-installed-inventory.json')
    write(inventory_path.name,{'module':module_name,'head':heads[module_name],'wheel':str(wheel),'wheel_sha256':wheel_record['sha256'],'assets':assets,'byte_equal':True,'missing_extra':[]})
    direct=origins[distname];assert direct is not None
    if module_name=='toad':
        assert direct['url']==wheel.as_uri() and 'archive_info' in direct
    source=FieldCodec.decode(InstalledSource,{'module':module_name,'head':heads[module_name],'location':str(location),'files':len(members),'python_files':sum(n.endswith('.py') for n in members),'byte_equal':True,'direct_url':direct,'inventory_sha256':digest(inventory_path)})
    artifact=ReviewedArtifact(wheel,wheel_record['sha256'])
    source.require_package(module_name,location,direct,(artifact,))
    sources.append(source);artifacts.append(artifact);inventories[module_name]={'path':str(inventory_path),'sha256':digest(inventory_path)}
assert sum(s.files for s in sources)==953
native=g['matching_native_reference'];native_path=Path(native['package'])
assert read['native_package']==str(native_path) and read['native_manifest']==native['manifest'] and read['native_tree']==native['tree']
assert digest(MANIFEST)==native['manifest'];verify_native_package(native_path)
assert package_tree_digest(native_path)==native['tree']
write('native-full-trust.json',{'authority':str(AUTHORITY),'authority_sha256':authority_sha,'native_package':str(native_path),'native_manifest':native['manifest'],'native_tree':native['tree'],'native_full_trust':True,'native_execution':False,'native_writes':False})
package_tuple=tuple(sorted(packages.items()));sdk=metadata.version('agent-client-protocol');assert sdk=='0.12.1'
requirements_sha=hashlib.sha256(json.dumps(package_tuple,separators=(',',':')).encode()).hexdigest()
proof=replace(prior,state='HELD466 source953/full69 actual485CURRENT459; oneNoAgent App unrun',prefix=prefix,sources=tuple(sources),native_package=native_path,native_cli=str(native_path/'dist/cli.js'),native_manifest=native['manifest'],native_tree=native['tree'],native_full_trust=True,sdk=sdk,package_count=69,packages=package_tuple,requirements_sha256=requirements_sha,protected_old_prefix_files=g['protected_originals_count'],protected_old_prefix_files_unchanged=True,public_install_changed=False,new_native_build=False,source_overlay=False,dependency_bypass=False,journey_owners=('OriginalEinstein466 one085b NoAgent viewport worker after literal release',),journey_assessment='OnlyToad normalb2e filewheel changes, truthful declared675Core/67Text retained; original68 distributions RAWorigins/1865other65 records/266protected and original485PREFIXactivation unchanged. No fake MAIN/fullwheel equality or Git filewheel metadata. Original7aFullTrust READ-only; no artifact execution/ACP/SDK/provider/input. App remains held.',archive_artifacts=tuple(artifacts))
activation=FieldCodec.decode(CohortActivation,{'stage':str(prefix),'pins':{s.module:s.head for s in sources if s.module!='textual_diff_view'},'sdk':sdk,'textual_diff_view':heads['textual_diff_view'],'native_package':str(native_path),'state':'HELD466 private own NoAgent candidate only; no publication or runtimecarry','staging_receipt':str(OUT/'candidate-source-proof.json'),'bins':{n:str(prefix/'bin'/n) for n in ('python','toad','agent-comms','agent-comms-acp','agent-comms-agent','pi-comms-native')},'native_cli':str(native_path/'dist/cli.js'),'native_manifest':native['manifest'],'native_tree':native['tree'],'native_configuration_note':'Actual issued09bc target+NEW matchingSchREAD-only; original085b App held until Bohr final953 proof binding/release. OwnDTO only; oldPREFIXactivation untouched.'})
proof.require_activation(activation)
write('candidate-source-proof.json',FieldCodec.encode(proof));write('candidate-activation.json',FieldCodec.encode(activation))
write('candidate-packages.json',{'versions':packages,'origins':origins})
write('package-boundary-proof.json',{'grant':str(GRANT),'issued_sha256':grant_sha,'source_assets':953,'source_inventories':inventories,'buildmetadata_RECORD':buildmetadata,'packages':69,'sdk':sdk,'other68_versions_RAWorigins_unchanged':True,'other65_files_unchanged':len(g['unchanged_other65_records']),'protected_originals_unchanged':len(g['protected_originals']),'PREFIXactivation_unchanged':True,'native_full_trust':True,'App_runs':0,'native_EXEC':False,'ACP_SDK_provider_input':False,'source_overlay':False})
print(json.dumps({'state':'SOURCE PROOF PASS; App HELD','assets':953,'packages':69,'protected':len(g['protected_originals']),'proof_sha256':digest(OUT/'candidate-source-proof.json'),'DTO_sha256':digest(OUT/'candidate-activation.json'),'boundary_sha256':digest(OUT/'package-boundary-proof.json'),'native_READ_receipt_sha256':digest(OUT/'native-full-trust.json')}),flush=True)
