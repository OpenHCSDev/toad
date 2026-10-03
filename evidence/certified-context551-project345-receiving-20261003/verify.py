from pathlib import Path
import hashlib, io, json, subprocess, tarfile, importlib, importlib.metadata as md, sys, os
wt=Path('/home/ts/wt/comms-task-aware-native-bundle-20261002')
out=Path('/home/ts/wt/toad-prompt-action-owner-20261002/.artifacts/certified-context551-project345-receiving-20261003'); prefix=Path('/home/ts/wt/toad-s5-receiving-boundary-pair-20261001/.artifacts/runtime-historical-handling290-current-20261001')
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
from agent_comms.native_package import MANIFEST,COMPACTION_HELPER,package_tree_digest
native=Path(owner['native']); previous=json.loads((out/'original345-installed-proof'/'source-proof.json').read_text()); assert native==Path(previous['native_package']); trusted_cli=previous['native_cli']; assert previous['native_full_trust'] is True
manifest=MANIFEST.read_bytes(); manifest_hash=hashlib.sha256(manifest).hexdigest()
assert manifest_hash==previous['native_manifest']
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
before=json.loads((wt/'.artifacts/summary-generation-policy520-installed-20261002/protected-before.json').read_text()); changed=[]
for name,digest in before.items():
 p=Path(name)
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest: changed.append(name)
assert not changed,changed[:10]
receipt={'state':'Merged551/345/341 normal69 installed source proof; original native960 fulltrust reused unchanged','prefix':str(prefix),'sources':sources,'native_package':str(native),'native_cli':str(trusted_cli),'native_manifest':manifest_hash,'native_tree':previous['native_tree'],'native_full_trust':True,'sdk':sdk,'package_count':len(packages),'packages':packages,'requirements_sha256':hashlib.sha256((out/'requirements.txt').read_bytes()).hexdigest(),'protected_old_prefix_files':len(before),'protected_old_prefix_files_unchanged':True,'public_install_changed':False,'new_native_build':False,'source_overlay':False,'dependency_bypass':False,'journey_owners':['Schrodinger client lifetime and original unchanged recovery; Mendel existing native context; Lovelace sole physical context Tree journey'],'journey_assessment':'Final normal551/345/341 merged source inventory/directURLs and unchanged native960 trust; original551 retained-writer/CLI and345/309 physical plus341 native06/physical startup receipts reused without rerun. Parent owns default acceptance after one quiet index operation.'}
(out/'source-proof.json').write_text(json.dumps(receipt,indent=2)+'\n')

print(json.dumps({'sources':[{k:v for k,v in s.items() if k in ('module','head','files','byte_equal')} for s in sources],'native_full_trust':True,'sdk':sdk,'package_count':len(packages),'prefix':str(prefix)},indent=2))
