"""Read published carry through original journal observation and declaration owners."""
from pathlib import Path
from dataclasses import replace
import hashlib,json,sys,time
wt=Path('/home/ts/wt/toad-prompt-action-owner-20261002')
out=wt/'.artifacts/task-aware520-fork-carry538-receiving-20261002/combined542'
sys.path.insert(0,str(out.parent/'stopped-installation541-final/operator-freeze'))
from native_schema_carry import NativeSchemaCarryPlan,rows,row_digest,digest
from agent_comms.field_codec import FieldCodec
from agent_comms.compaction_journal import CompactionJournal
from agent_comms.compaction_records import JournalTable
from agent_comms.typed_table import TypedTable
prep=out/'operator-preparation';pub=prep/'publication-receipt.json';raw=pub.read_bytes();r=json.loads(raw)
carry=Path(r['runtime_installation']['original_preimages']);plan=FieldCodec.decode(NativeSchemaCarryPlan,json.loads((carry/'reviewed-carry.json').read_text()))
tables={t.declared_name:t for t in TypedTable.members_with(JournalTable)}
assert len(tables)==6
for store in plan.stores:
 assert digest(carry/store.name)==store.original_sha256,store.name
store=next(s for s in plan.stores if s.name=='compaction-commits.sqlite3')
def identities(db):
 # Read owner returns sqlite.Row; carry evidence used tuples. Compare SQL cells,
 # never row-object repr addresses, in the original carry's ordering.
 return {name:sorted((tuple(row) for row in rows(db,name,fields if tables[name].without_rowid else ('rowid',*fields))),key=repr) for name,fields in plan.original.compaction_columns.items()}
def original(db):
 plan.original.require_compaction(db)
 return identities(db)
old=CompactionJournal.observe_readonly(carry/'compaction-commits.sqlite3',original,absent=None)
assert old is not None and row_digest(old)==store.evidence['original_identity_rows_sha256']
def current(db):
 plan.target.require_compaction(db)
 counts={name:len(t.select(db)) for name,t in tables.items()}
 now=identities(db)
 return counts,now
counts,now=CompactionJournal.observe_readonly(plan.root/'compaction-commits.sqlite3',current,absent=None)
assert counts['native_fork_creation']==0,counts
assert now==old,'Original journal rows changed after publication; record owned transition before claiming preservation'
assert pub.read_bytes()==raw
result={'state':'Published carry actual six typed journal readers and original preimage identity relation PASS','observed_at':time.time(),'target_python':sys.executable,'raw_publication_sha256':hashlib.sha256(raw).hexdigest(),'raw_publication_phase':r['phase'],'typed_reader_counts':counts,'native_fork_creation_empty':True,'authentic_preimage_hashes':{s.name:s.original_sha256 for s in plan.stores},'all_original_journal_rowids_cells_source_and_unknown_equal':True,'original_identity_rows_sha256':row_digest(old),'same_installed_original_identity_rows_sha256':row_digest(now),'source_release':plan.original.release_versions,'target_release':plan.target.release_versions,'schema_relation':'Same Native6 release; only declared empty native_fork_creation addition. No retroactive proof or input admission minted.','read_owner':'CompactionJournal.observe_readonly + all TypedTable JournalTable members; no writer constructor/transaction','public_writes':0,'native_inputs':0,'provider_calls':0,'publication_repeated':False}
p=prep/'publication-carry-readback.json';assert not p.exists();p.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
