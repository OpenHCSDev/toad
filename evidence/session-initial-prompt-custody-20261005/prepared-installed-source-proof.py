"""Issued source/native READ proof only; original receipt owners, no App launch."""
import csv,hashlib,importlib,importlib.metadata as metadata,io,json,os,stat,sys,zipfile
from dataclasses import replace
from pathlib import Path
GRANT=Path(sys.argv[1]); grant_sha=sys.argv[2]
AUTHORITY=Path(sys.argv[3]); authority_sha=sys.argv[4]
OUT=Path(sys.argv[5])
def digest(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def write(path,value):
 with path.open('x') as stream:stream.write(json.dumps(value,indent=2)+'\n')
assert digest(GRANT)==grant_sha
g=json.loads(GRANT.read_text());l=json.loads(Path(g['lifecycle']).read_text())
assert l['proof_execution_authorized'] and l['native_READ_authorized'] and not l['execution_authorized'] and not l['native_EXEC_authorized']
assert digest(AUTHORITY)==authority_sha
read_authority=json.loads(AUTHORITY.read_text())
assert read_authority['holder_grant']=={'path':str(GRANT),'sha256':grant_sha}
assert read_authority['native_READ_authorized'] and not read_authority['native_EXEC_authorized']
assert OUT==Path(g['owned_output'])
prefix=Path(g['prefix']);assert Path(sys.prefix)==prefix and not os.environ.get('PYTHONPATH') and not os.environ.get('PYTHONHOME')
for record in g['unchanged_other66_records']:
 p=Path(record['path']);assert stat.S_IMODE(p.lstat().st_mode)==record['mode'],p
 if record['kind']=='symlink':assert os.readlink(p)==record['target'],p
 else:assert digest(p)==record['sha256'],p
for keeper in ['protected_originals','separate_original448_wrapperkeepers']:
 for name,expected in g[keeper].items():
  p=Path(name);assert digest(p)==expected['sha256'] and stat.S_IMODE(p.stat().st_mode)==expected['mode'],p
assert digest(g['actual_PREFIXactivation']['path'])==g['actual_PREFIXactivation']['sha256']
assert digest(g['control']['path'])==g['control']['sha256'] and digest(g['control']['helper'])==g['control']['helper_sha256']
packages={d.metadata['Name']:d.version for d in metadata.distributions()};assert packages==g['normal_distributions'] and len(packages)==69
for name,original in g['original69_origins'].items():
 if name in ('agent-comms','batrachian-toad','textual'):continue
 text=metadata.distribution(name).read_text('direct_url.json');assert (None if text is None else json.loads(text))==(None if original is None else original['contents']),name
# Existing canonical typed receipt owner, byte equal to the selected Core tool.
sys.path.insert(0,'/home/ts/wt/comms-field-codec-closure-20260928/tools/cutover')
from publish_retained_summary import CohortActivation,InstalledSourceProof,InstalledSource,ReviewedArtifact
from agent_comms.field_codec import FieldCodec
from agent_comms.native_package import verify_native_package,package_tree_digest,MANIFEST
prior_path=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/context-explorer-functional-receiving-20261004/source-proof.json')
assert digest(prior_path)=='8a8fd8201d4357e648d55979340bce16ab2d7e89d6db1fbe8f312de1e1cbc578'
prior=FieldCodec.decode(InstalledSourceProof,json.loads(prior_path.read_text()))
inputs=[('agent_comms','agent-comms',g['candidate_dependency_filewheels'][0]['head'],Path(g['candidate_dependency_filewheels'][0]['path']),g['candidate_dependency_filewheels'][0]['sha256']),('toad','batrachian-toad',g['determining_union'],Path(g['candidate_Toad_filewheel']['path']),g['candidate_Toad_filewheel']['sha256']),('textual','textual',g['candidate_dependency_filewheels'][1]['head'],Path(g['candidate_dependency_filewheels'][1]['path']),g['candidate_dependency_filewheels'][1]['sha256'])]
installed=prefix/'lib/python3.14/site-packages'
# The remaining original sources are unchanged by this stage and retain their origins.
for module,dist in [('refactor_audit','nominal-refactor-audit')]:
 source=next(s for s in prior.sources if s.module==module)
 r=next(r for r in g['restore_filewheels'] if r['module']==module);wheel=Path(r['path']);wheel_sha=r['sha256']
 inputs.append((module,dist,source.head,wheel,wheel_sha))
# Original cold460 proof acquires Diff's authentic cached wheel; VCS origin stays VCS.
diff=next(s for s in prior.sources if s.module=='textual_diff_view')
inputs.append((diff.module,'textual-diff-view',diff.head,Path('/home/ts/.cache/uv/sdists-v9/git/6a8a377ce2150d3f/8fa7d4d0db993ea3/textual_diff_view-0.1.5-py3-none-any.whl'),'be7089c8f282e07e893b0254a0859e0f1b243a7ba591749f2053fa1fb775ad36'))
sources=[];artifacts=[];inventories={};metadata_records={}
for module_name,distname,head,wheel,wheel_sha in inputs:
 assert digest(wheel)==wheel_sha
 module=importlib.import_module(module_name);location=Path(module.__file__).parent;assert location.parent==installed,location
 with zipfile.ZipFile(wheel) as archive:
  members=sorted(n for n in archive.namelist() if n.startswith(module_name+'/') and not n.endswith('/'));inventory=[]
  for member in members:
   raw=archive.read(member);sha=hashlib.sha256(raw).hexdigest();assert digest(installed/member)==sha,member
   inventory.append({'member':member,'bytes':len(raw),'sha256':sha})
  actual={str(p.relative_to(installed)) for p in location.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'};assert actual==set(members),(module_name,actual.symmetric_difference(members))
  if module_name in ('agent_comms','toad','textual'):
   record=next(n for n in archive.namelist() if n.endswith('.dist-info/RECORD'));entries=list(csv.reader(io.StringIO(archive.read(record).decode())))
   import base64
   for n,encoded,size in entries:
    raw=archive.read(n)
    if encoded:
     algorithm,hash_=encoded.split('=',1);assert base64.urlsafe_b64encode(hashlib.new(algorithm,raw).digest()).rstrip(b'=').decode()==hash_;assert len(raw)==int(size)
    else:assert n==record
    if '.dist-info/' in n and n!=record:assert (installed/n).read_bytes()==raw,n
   metadata_records[module_name]={'raw_record_entries':len(entries),'buildmetadata_installed_byte_equal':True}
 inventory_path=OUT/(module_name+'-installed-inventory.json');write(inventory_path,{'module':module_name,'wheel':str(wheel),'wheel_sha256':wheel_sha,'assets':inventory,'byte_equal':True,'missing_extra':[]})
 text=metadata.distribution(distname).read_text('direct_url.json');assert text is not None;direct=json.loads(text)
 if module_name in ('agent_comms','toad','textual'):assert direct['url']==wheel.as_uri(),direct
 else:assert direct==g['original69_origins'][distname]['contents']
 source=FieldCodec.decode(InstalledSource,{'module':module_name,'head':head,'location':str(location),'files':len(members),'python_files':sum(n.endswith('.py') for n in members),'byte_equal':True,'direct_url':direct,'inventory_sha256':digest(inventory_path)})
 artifact=ReviewedArtifact(wheel,wheel_sha);source.require_package(module_name,location,direct,(artifact,));sources.append(source);artifacts.append(artifact);inventories[module_name]={'path':str(inventory_path),'sha256':digest(inventory_path)}
assert sum(s.files for s in sources)==953
assert digest(installed/'refactor_audit/measures.py')=='8f6127cb184801fbf2ca162adbece5c103c0fc6693f81197632668f710af7513'
native=g['matching_native_reference'];native_path=Path(native['package']);assert digest(MANIFEST)==native['manifest'];verify_native_package(native_path);assert package_tree_digest(native_path)==native['tree']
write(OUT/'native-full-trust.json',{'authority':str(AUTHORITY),'authority_sha256':digest(AUTHORITY),'package':str(native_path),'manifest':native['manifest'],'tree':native['tree'],'native_full_trust':True,'artifact_execution':False,'artifact_writes':False})
package_tuple=tuple(sorted(packages.items()));sdk=metadata.version('agent-client-protocol');assert sdk=='0.12.1';requirements_sha=hashlib.sha256(json.dumps(package_tuple,separators=(',',':')).encode()).hexdigest()
proof=replace(prior,state='HELD461 own953/full69 CURRENT448 artifact proof; exactNoAgentApp unrun',prefix=prefix,sources=tuple(sources),native_package=native_path,native_cli=str(native_path/'dist/cli.js'),native_manifest=native['manifest'],native_tree=native['tree'],native_full_trust=True,sdk=sdk,package_count=69,packages=package_tuple,requirements_sha256=requirements_sha,protected_old_prefix_files=626,protected_old_prefix_files_unchanged=True,public_install_changed=False,new_native_build=False,source_overlay=False,dependency_bypass=False,journey_owners=('OriginalEinstein461 exact85fcNoAgent after bound release',),journey_assessment='Original953/full69 source/artifact/typed origin proof only; other66/1883+626keepers+5originalwrappers/PREFIXactivation unchanged. NativeREAD only/no App/nativeprocess/SDK/ACP/provider/input. Diff bytes acquired from authentic cached wheel; original VCS installer origin retained. Two local preadmissionUIevents only under later fresh release.',archive_artifacts=tuple(artifacts))
activation=FieldCodec.decode(CohortActivation,{'stage':str(prefix),'pins':{s.module:s.head for s in sources if s.module!='textual_diff_view'},'sdk':sdk,'textual_diff_view':next(s.head for s in sources if s.module=='textual_diff_view'),'native_package':str(native_path),'state':'HELD461 private CURRENT448 independentNoAgent candidate; no public operation','staging_receipt':str(OUT/'candidate-source-proof.json'),'bins':{n:str(prefix/'bin'/n) for n in ('python','toad','agent-comms','agent-comms-acp','agent-comms-agent','pi-comms-native')},'native_cli':str(native_path/'dist/cli.js'),'native_manifest':native['manifest'],'native_tree':native['tree'],'native_configuration_note':'Fresh literal holder grant and matching native READ authority are passed to this proof and validated. Original85fc App remains held until finalproof/DTO/release. No artifact EXEC or public operation. Actual floor/restoration are owned by the fresh issued grant.'})
proof.require_activation(activation)
write(OUT/'candidate-source-proof.json',FieldCodec.encode(proof));write(OUT/'candidate-activation.json',FieldCodec.encode(activation))
write(OUT/'package-boundary-proof.json',{'issued_sha256':digest(GRANT),'source_assets':953,'source_inventories':inventories,'buildmetadata_RECORD':metadata_records,'package_count':69,'packages':package_tuple,'other66_files_unchanged':1883,'protected_originals_unchanged':626,'separate_wrappers_unchanged':5,'PREFIXactivation_unchanged':True,'sdk':sdk,'native_full_trust':True,'Apps_run':0,'native_execution':False})
write(OUT/'candidate-packages.json',{'versions':packages,'origins':{n:metadata.distribution(n).read_text('direct_url.json') for n in packages}})
print(json.dumps({'state':'SOURCE PROOF PASS; App HELD','source_assets':953,'packages':69,'sdk':sdk,'protected':626,'wrappers':5,'proof_sha256':digest(OUT/'candidate-source-proof.json'),'DTO_sha256':digest(OUT/'candidate-activation.json'),'boundary_sha256':digest(OUT/'package-boundary-proof.json'),'native_trust_sha256':digest(OUT/'native-full-trust.json')}),flush=True)
