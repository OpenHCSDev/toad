import concurrent.futures
import json
import os
from pathlib import Path
import subprocess

root=Path('/home/ts/wt/toad-export-caller-migration-20260928')
python='/home/ts/.local/share/agent-comms/runtime-manual-owner-20260928/bin/python'
scripts=['async_thread_open_pilot','hot_path_invalidation_pilot','in_out_filter_pilot','message_categories_pilot','off_tail_checkpoint_pilot','thread_unread_start_pilot']
def run(name):
 env=os.environ.copy();env['PYTHONPATH']='/home/ts/wt/comms-refactor-s7-wire-log-20260928/src:'+str(root/'src')
 with (root/'evidence/s7-consumers'/f'{name}.log').open('w') as log:
  try:
   result=subprocess.run([python,str(root/'tests'/f'{name}.py')],env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=60)
   code=result.returncode
  except subprocess.TimeoutExpired:code=124
 row={'script':name,'exit':code};print(json.dumps(row),flush=True);return row
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 results=list(pool.map(run,scripts))
(root/'evidence/s7-consumers/remaining-results.json').write_text(json.dumps(results,indent=2)+'\n')
