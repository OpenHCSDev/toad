"""Original SDK task survives native process delivery after its owner move."""
import asyncio
from toad.acp.sdk_boundary import ValidateSessionUpdateTask, AcceptedSessionUpdateValidation, RejectedSessionUpdateValidation
from toad.render_processes import RenderProcessPool

async def main():
    pool = RenderProcessPool(max_workers=1, max_pending=1)
    try:
        task = ValidateSessionUpdateTask('owned', {'sessionUpdate':'agent_message_chunk', 'content':{'type':'text','text':'original SDK task'}})
        result = task.accept_result(await pool.submit(task))
        assert isinstance(result, AcceptedSessionUpdateValidation)
        assert result.notification.update.content.text == 'original SDK task'
        invalid = ValidateSessionUpdateTask('owned', {'sessionUpdate':'nonexistent'})
        assert isinstance(invalid.accept_result(await pool.submit(invalid)), RejectedSessionUpdateValidation)
        print('PASS original task through real spawned worker; typed result and external invalid-update refusal')
    finally:
        await pool.aclose()

if __name__ == '__main__':
    asyncio.run(main())
