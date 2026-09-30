"""Bounded cleanup-resource proof; this does not run or certify a UI journey."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import psutil
import runtime_fixture as fixture


class OriginalRunFailure(Exception):
    pass


@asynccontextmanager
async def interrupted_context(self, **kwargs):
    # Only the context boundary is controlled. No UI/protocol mock is accepted
    # as readiness; the real owned OS child and original cleanup are exercised.
    yield object()


async def main():
    attempt = 'fixture-cleanup-source-20260930'
    root = Path(__file__).resolve().parents[1] / 'evidence/native-fixture-cleanup-20260930/private-source-probe'
    original = OriginalRunFailure('Original interrupted run must remain in the error chain')
    locks_called = []

    class Route:
        def observe_root(self):
            return root

    def failed_owner_wait(selected_root):
        assert selected_root == root
        raise psutil.TimeoutExpired(10, pid=child.pid)

    with patch.dict(os.environ, {'TOAD_TEST_ATTEMPT': attempt}):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            with (patch.object(fixture, 'resolve_comms_route', return_value=Route()),
                  patch.object(fixture.Application, 'run_test', interrupted_context),
                  patch.object(fixture, 'stop_test_owners', failed_owner_wait),
                  patch.object(fixture, '_clear_wire_locks', locks_called.append)):
                try:
                    async with fixture.ToadApp.run_test(object.__new__(fixture.ToadApp)):
                        raise original
                except psutil.TimeoutExpired as error:
                    assert error.__context__ is original
                else:
                    raise AssertionError('Original cleanup failure was swallowed')
            child.wait(timeout=3)
            assert locks_called == [root]
            print(json.dumps({'scope': 'fixture cleanup source and actual owned OS child only',
                              'owner_wait_failure_preserved': True,
                              'original_run_failure_preserved_in_chain': True,
                              'actual_owned_child_pid': child.pid,
                              'actual_owned_child_exited': child.returncode is not None,
                              'final_original_cleanup_called': True,
                              'ui_native_readiness_claim': False,
                              'native_inputs': 0, 'provider_calls': 0}))
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=3)


if __name__ == '__main__':
    asyncio.run(main())
