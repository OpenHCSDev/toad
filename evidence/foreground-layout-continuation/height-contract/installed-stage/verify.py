import hashlib,importlib,importlib.metadata as md,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
out=Path(__file__).parent
stage=Path(sys.prefix)
donor=Path('/home/ts/wt/toad-foreground-readiness-remainder-20260930/.artifacts/runtime-reader-geometry-254-20261001')
head=json.loads((out/'build.json').read_text())['source']
script="import importlib.metadata as m,json; print(json.dumps({d.metadata['Name'].lower():[d.version,json.loads(d.read_text('direct_url.json') or 'null')] for d in m.distributions()}))"
old=json.loads(subprocess.check_output([str(donor/'bin/python'),'-c',script],text=True))
new=json.loads(subprocess.check_output([sys.executable,'-c',script],text=True))
assert old.keys()==new.keys() and len(new)==69,(len(old),len(new))
for name, value in old.items():
 if name!='batrachian-toad': assert value==new[name],name
assert new['batrachian-toad'][1]['vcs_info']['commit_id']==head
assert not new['batrachian-toad'][1].get('dir_info',{}).get('editable')
proof=json.loads((Path('/home/ts/wt/toad-foreground-readiness-remainder-20260930/evidence/native-applied-cohort-pair-20261001/package/package-source-trust.json')).read_text())
print('proof keys',list(proof))
source_proof=proof.get('source_proof',proof)
verified={}
for dist, modname in [('agent-comms','agent_comms'),('textual','textual')]:
 module=importlib.import_module(modname)
 package=Path(module.__file__).parent
 expected=source_proof[dist]['sha256']
 prefix='src/'+modname+'/'
 for path,digest in expected.items():
  assert path.startswith(prefix),path
  installed=package/path.removeprefix(prefix)
  assert hashlib.sha256(installed.read_bytes()).hexdigest()==digest,path
 verified[dist]={'count':len(expected),'original_git_source_sha256':expected}
package=Path(importlib.import_module('toad').__file__).parent
paths=subprocess.check_output(['git','ls-tree','-r','--name-only',head,'src/toad'],cwd=root,text=True).splitlines()
for path in paths:
 installed=package/path.removeprefix('src/toad/')
 data=subprocess.check_output(['git','show',head+':'+path],cwd=root)
 assert installed.read_bytes()==data,path
verified['batrachian-toad']={'count':len(paths),'commit':head}
from agent_comms.native_package import verify_native_package
native=Path('/home/ts/.local/share/agent-comms/native-current-593b978a717ae8f6/node_modules/@earendil-works/pi-coding-agent')
verify_native_package(native)
import toad.cli,toad.transcript_publication,toad.widgets.viewport_body,toad.screens.workspace,agent_comms.acp
activation=json.loads((donor/'activation.json').read_text())
activation.update(stage=str(stage),state='staged-not-default')
activation['pins']['batrachian-toad']=head
activation.pop('staging_receipt_sha256',None)
activation['staging_receipt']=str(out/'verified.json')
p=stage/'activation.json';p.write_text(json.dumps(activation,indent=2)+'\n');p.chmod(0o600)
receipt={'state':'STAGED-SOURCE-TRUST-PASS','stage':str(stage),'source':head,'pins':activation['pins'],'sdk':'0.12.1','native_package':str(native),'distribution_count':len(new),'all_donor_dependencies_identical':True,'source_proof':verified,'imports':'PASS','native_full_tree_trust':'PASS','public_effects':0,'installed_ui_acceptance':'pending'}
(out/'verified.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('PASS',len(new),'distributions', {k:v['count'] for k,v in verified.items()},'native full tree','activation600')
