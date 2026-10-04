from pathlib import Path
import hashlib, io, json, subprocess, tarfile, importlib, importlib.metadata as md, sys, os
wt=Path('/home/ts/wt/comms-task-aware-native-bundle-20261002')
out=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/frame-work418-native610-receiving-20261004'); prefix=Path('/home/ts/wt/comms-goal-ledger-schema-carry-20261002/.artifacts/runtime-scoped-input534')
owner=json.loads((out/'ownership.json').read_text()); assert Path(sys.prefix)==prefix
sys.path.insert(0,str(out/'operator-freeze'))
from publish_retained_summary import InstalledSource,VcsPackageDirectUrl,ArchivePackageDirectUrl,ReviewedArtifact
from agent_comms.field_codec import FieldCodec
artifacts=FieldCodec.decode(tuple[ReviewedArtifact,...],owner['archive_artifacts'])
sources=[]
for name,repo,head,dist in [
 ('agent_comms','/home/ts/wt/comms-task-aware-native-bundle-20261002',owner['core'],'agent-comms'),
 ('toad','/home/ts/wt/toad-prompt-action-owner-20261002',owner['toad'],'batrachian-toad'),
 ('textual','/home/ts/wt/textual-main',owner['textual'],'textual'),
 ('textual_diff_view','/home/ts/wt/textual-diff-native-geometry-20261001','8fa7d4d0db993ea3b761c2760ca9b6a56a6251e9','textual-diff-view')]:
 mod=importlib.import_module(name); location=Path(mod.__file__).parent
 assert location.is_relative_to(prefix),str(location)
 archive=subprocess.check_output(['git','-C',repo,'archive',head,'src/'+name])
 inventory=[]
 with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
  for member in tar.getmembers():
   if not member.isfile(): continue
   relative=Path(member.name).relative_to('src')
   raw=tar.extractfile(member).read(); installed=location.parent/relative
   assert installed.is_file(),f'Missing {name}: {relative}'
   assert installed.read_bytes()==raw,f'Mismatch {name}: {relative}'
   inventory.append({'path':str(relative),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
 direct=json.loads(md.distribution(dist).read_text('direct_url.json'))
 origin=FieldCodec.decode(VcsPackageDirectUrl|ArchivePackageDirectUrl,direct)
 source=InstalledSource(name,head,str(location),len(inventory),sum(i['path'].endswith('.py') for i in inventory),True,origin,hashlib.sha256(json.dumps(inventory,sort_keys=True).encode()).hexdigest())
 source.require_original(artifacts)
 sources.append(FieldCodec.encode(source))
 (out/(name+'-inventory.json')).write_text(json.dumps(inventory,indent=2)+'\n')
# Native import seam is checked without mounting or sending any input.
import toad.widgets.tool_call
import toad.acp.maintenance_ingress
import toad.acp.agent_process
import toad.acp.context_measurement
from agent_comms.native_package import MANIFEST,COMPACTION_HELPER,package_tree_digest,verify_native_package
native=Path(owner['native']); artifact=json.loads((out/'native-artifact-receipt.json').read_text()); assert native==Path(artifact['canonical_package']); trusted_cli=str(native/'dist/cli.js'); previous={'native_manifest':artifact['manifest'],'native_tree':artifact['tree']}
manifest=MANIFEST.read_bytes(); manifest_hash=hashlib.sha256(manifest).hexdigest()
assert manifest_hash==previous['native_manifest']; verify_native_package(native)
for original,target in [('stack/pi-native.sha256',MANIFEST),('stack/native-compaction-commit-child.mjs',COMPACTION_HELPER)]:
 expected=subprocess.check_output(['git','-C','/home/ts/wt/comms-task-aware-native-bundle-20261002','show',owner['core']+':'+original])
 assert target.read_bytes()==expected,original
for name in ('toad','agent-comms','agent-comms-acp','agent-comms-agent','pi-comms-native'):
 p=prefix/'bin'/name; assert p.is_file() and os.access(p,os.X_OK)
 interpreter=str(prefix/'bin/python')
 # Verify the installer's complete standard POSIX interpreter declaration.
 expected=(['#!'+interpreter] if len(interpreter.encode())+3<=127 else
           ['#!/bin/sh', "'''exec' '"+interpreter+"' \"$0\" \"$@\"", "' '''"])
 assert p.read_text().splitlines()[:len(expected)]==expected,p
sdk=md.version('agent-client-protocol'); packages=sorted((d.metadata['Name'],d.version) for d in md.distributions())
assert sdk=='0.12.1' and len(packages)==69,(sdk,len(packages))
before=json.loads((out/'protected-before.json').read_text()); changed=[name for name,digest in before.items() if not Path(name).is_file() or hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest]; assert not changed,changed
receipt={'state':'Normal qualified418/Text50 on retainedCore611/native2ea; original file wheels and normal69','prefix':str(prefix),'sources':sources,'native_package':str(native),'native_cli':str(trusted_cli),'native_manifest':manifest_hash,'native_tree':previous['native_tree'],'native_full_trust':True,'sdk':sdk,'package_count':len(packages),'packages':packages,'requirements_sha256':hashlib.sha256((out/'requirements.txt').read_bytes()).hexdigest(),'protected_old_prefix_files':len(before),'protected_old_prefix_files_unchanged':True,'public_install_changed':False,'new_native_build':False,'source_overlay':False,'dependency_bypass':False,'archive_artifacts':FieldCodec.encode(artifacts),'journey_owners':['Original418 joined Core611/native2ea actual138.053s input-warm/16warm/7input; inherited603/610/611/menu/currentcontext source scopes retained'],'journey_assessment':'Installed source proof of normal419/Core611/Text50/native2ea; original wheels reused with truthful archive provenance and normal69. Original418 qualification retained; discrete positions remain/no CPU or smoothness claim. Recorded417/unreviewed608/new614 excluded. Parent actual ordinary default assembly acceptance follows publication.'}
(out/'source-proof.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'sources':[{k:v for k,v in s.items() if k in ('module','head','files','byte_equal')} for s in sources],'native_full_trust':True,'sdk':sdk,'package_count':len(packages),'prefix':str(prefix)},indent=2))
