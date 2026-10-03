import asyncio,json,multiprocessing,subprocess,sys,time
from pathlib import Path
from toad.acp.agent_controller import ApplicationValidationOwner,HeadlessValidationOwner
from toad.acp.sdk_boundary import ValidateSessionUpdateTask,AcceptedSessionUpdateValidation
from toad.render_processes import RenderProcessPool
async def main():
    start=time.perf_counter()
    initial={p.pid for p in multiprocessing.active_children()}
    pool=RenderProcessPool(max_workers=1,max_pending=1)
    task=ValidateSessionUpdateTask("receiving567366",{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"Receiving worker SDK validation"}})
    try:
        headless=await HeadlessValidationOwner().validate(task)
        local=await ApplicationValidationOwner(pool).validate(task)
        assert isinstance(headless,AcceptedSessionUpdateValidation) and isinstance(local,AcceptedSessionUpdateValidation)
        assert headless.notification.update.content.text==local.notification.update.content.text=="Receiving worker SDK validation"
    finally:
        await pool.aclose()
    assert not pool._pending and {p.pid for p in multiprocessing.active_children()}==initial
    result={"state":"PASS","python":sys.executable,"elapsed_seconds":time.perf_counter()-start,"scope":"Actual installed application local spawn and headless SDK result acceptance on combined567366 baseline69; no persistent-extra or physical/provider claim","owned_children_remaining":[],"native_inputs":0,"provider_calls":0,"public_inputs":0}
    Path(__file__).with_name("installed-entrypoint-worker-receipt.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
if __name__=="__main__":asyncio.run(main())
