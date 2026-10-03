from pathlib import Path
import hashlib, io, json, subprocess, tarfile, importlib, importlib.metadata as md, sys, os
wt=Path('/home/ts/wt/comms-task-aware-native-bundle-20261002')
out=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/catalog-retained-construction388-receiving-20261003'); prefix=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/runtime-native-read532-534-retirement325-20261002')
owner=json.loads((out/'ownership.json').read_text()); assert Path(sys.prefix)==prefix
sources=[]
for name,repo,head,dist in [
 ('agent_comms','/home/ts/wt/comms-task-aware-native-bundle-20261002',owner['core'],'agent-comms'),
 ('toad','/home/ts/wt/toad-prompt-action-owner-20261002',owner['toad'],'batrachian-toad'),
 ('textual','/home/ts/wt/textual-native-subtree-retirement-20261001',owner['textual'],'textual'),
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
 assert direct['vcs_info']['commit_id']==head,direct
 sources.append({'module':name,'head':head,'location':str(location),'files':len(inventory),'python_files':sum(i['path'].endswith('.py') for i in inventory),'byte_equal':True,'direct_url':direct,'inventory_sha256':hashlib.sha256(json.dumps(inventory,sort_keys=True).encode()).hexdigest()})
 (out/(name+'-inventory.json')).write_text(json.dumps(inventory,indent=2)+'\n')
# Native import seam is checked without mounting or sending any input.
import toad.widgets.tool_call
import toad.acp.maintenance_ingress
import toad.acp.agent_process
import toad.acp.context_measurement
from agent_comms.native_package import MANIFEST,COMPACTION_HELPER,package_tree_digest,verify_native_package
native=Path(owner['native']); artifact=json.loads((out/'51b-artifact-receipt.json').read_text()); assert native==Path(artifact['canonical_package']); trusted_cli=str(native/'dist/cli.js'); previous={'native_manifest':artifact['manifest'],'native_tree':artifact['tree']}
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
receipt={'state':'Merged581580582/386/Text38 normal69 installed union source proof; native51b','prefix':str(prefix),'sources':sources,'native_package':str(native),'native_cli':str(trusted_cli),'native_manifest':manifest_hash,'native_tree':previous['native_tree'],'native_full_trust':True,'sdk':sdk,'package_count':len(packages),'packages':packages,'requirements_sha256':hashlib.sha256((out/'requirements.txt').read_bytes()).hexdigest(),'protected_old_prefix_files':len(before),'protected_old_prefix_files_unchanged':True,'public_install_changed':False,'new_native_build':False,'source_overlay':False,'dependency_bypass':False,'journey_owners':['Einstein386 installed01 actualApp/catalog/editor/realPTY','Mendel581 real configured42MB samechild commit-reload and distinct input;580582 recorded construction owners','Heis382/Text38 original105s scoped physical motion','Arendt573 configured manifest/request/budget and576 deep-root three-fork'],'journey_assessment':'Original581 configured42MB SolHIGH samechild commit-reload then distinct input actual124.474s qualification retained;386 actualApp/catalog/editor/realPTY and580582 recorded construction scopes retained. Original573576 configured and382Text38 motion proofs retained. No new provider/recording/native/environment, no fullS4 or speed claim.'}
(out/'source-proof.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'sources':[{k:v for k,v in s.items() if k in ('module','head','files','byte_equal')} for s in sources],'native_full_trust':True,'sdk':sdk,'package_count':len(packages),'prefix':str(prefix)},indent=2))
