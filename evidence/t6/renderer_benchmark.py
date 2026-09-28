import asyncio,json,statistics,tempfile,time
from pathlib import Path
from toad.render_service import RenderServiceConfig
from toad.render_tasks import PatchRenderTask
from toad.render_zmq import PersistentRendererPool,RendererEndpoint

async def main():
 with tempfile.TemporaryDirectory(prefix='render-bench-') as d:
  config=RenderServiceConfig(max_workers=2,max_pending=4)
  endpoint=await asyncio.to_thread(RendererEndpoint.for_runtime,Path(d),config)
  pool=PersistentRendererPool(endpoint,config)
  source='--- x.py\n+++ x.py\n@@ -1,80 +1,80 @@\n'+'-old = 123\n+new = 456\n'*80
  task=PatchRenderTask(source,False,True)
  gaps=[];done=False
  async def beat():
   previous=time.perf_counter()
   while not done:
    await asyncio.sleep(.005)
    now=time.perf_counter();gaps.append((now-previous)*1000);previous=now
  heartbeat=asyncio.create_task(beat())
  try:
   begin=time.perf_counter();expected=await pool.submit(task);cold=(time.perf_counter()-begin)*1000
   samples=[]
   for _ in range(21):
    begin=time.perf_counter();result=await pool.submit(task);samples.append((time.perf_counter()-begin)*1000)
    assert result.patch==expected.patch
   print(json.dumps({'cold_ms':round(cold,2),'warm_median_ms':round(statistics.median(samples),2),
     'warm_p95_ms':round(sorted(samples)[19],2),'heartbeat_max_ms':round(max(gaps),2),
     'samples':len(samples),'boundary':'actual installed persistent RPC and worker result parity'}))
  finally:
   done=True;await heartbeat;await pool.aclose();assert await pool.shutdown_service()
asyncio.run(main())
