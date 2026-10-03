"""Declared codecs, reply transitions, new cases and actual renderer admission."""

from __future__ import annotations

import asyncio
import pickle
import subprocess
import sys
from dataclasses import dataclass, fields
import unittest
from uuid import uuid4

from agent_comms.field_codec import FieldCodec
from toad.render_protocol import (
    RenderCommand,
    RenderReply,
    CapturedResult,
    SubmitRender,
    PollRender,
    AcknowledgeRender,
    AcceptedReply,
    BusyReply,
    PendingReply,
    CompleteReply,
    CancelledReply,
    FailedReply,
    RejectedReply,
    UnknownReply,
    AcknowledgedReply,
)
from toad.render_service import RenderService, RenderServiceConfig
from toad.render_tasks import PatchRenderTask
from toad.render_backend import RenderTask
from toad.render_zmq import RenderSubmission
from toad.widgets.agent_activity import AgentActivityBoundary
from toad.widgets.message_filter import (
    all_categories,
    MessageCategory,
    FromPerson,
    FromAgent,
    AgentWork,
)


@dataclass(frozen=True)
class CountRenderTask(RenderTask[int]):
    count: int

    def execute(self):
        return self.count

    def accept_result(self, result):
        if type(result) is not int:
            raise TypeError("Expected a count")
        return result


class ReactionClient:
    def __init__(self):
        self._client_id = uuid4()
        self._poll_interval = 0.00001
        self._closed = False
        self.acks = 0

    async def acknowledge(self, submission):
        self.acks += 1


class RenderingFamilyTests(unittest.IsolatedAsyncioTestCase):
    def test_captured_task_loads_its_declaring_module(self):
        """Detect eager native catalog loading and lost decode-before-admission."""
        encoded = FieldCodec.encode(SubmitRender(
            uuid4(), uuid4(), PatchRenderTask("--- a.py\n+++ a.py\n@@ -1 +1 @@\n-old\n+new\n", False, True),
        ))
        result = subprocess.run([sys.executable, "-c", """
import pickle,sys
from agent_comms.field_codec import FieldCodec
from toad.render_protocol import RenderCommand
assert 'toad.render_tasks' not in sys.modules
assert 'toad.widgets.patch_diff' not in sys.modules
assert 'toad.acp.sdk_boundary' not in sys.modules
command = FieldCodec.decode(RenderCommand, pickle.loads(sys.stdin.buffer.read()))
assert type(command.task).__module__ == 'toad.render_tasks'
assert command.task.execute().patch.after[0] == 'new'
print('declaring module loaded from captured task; generic transport had no frontend catalog')
"""], input=pickle.dumps(encoded), capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_commands_and_replies_round_trip(self):
        samples = dict(
            client_id=uuid4(),
            request_id=uuid4(),
            task=PatchRenderTask("patch", False, True),
            result=CapturedResult(9),
            error="worker error",
        )
        for family in (RenderCommand, RenderReply):
            for member in family.members_with(family):
                value = member(
                    **{
                        field.name: samples[field.name]
                        for field in fields(member)
                        if field.name in samples
                    }
                )
                self.assertEqual(
                    FieldCodec.decode(family, FieldCodec.encode(value)), value
                )
        encoded = FieldCodec.encode(
            SubmitRender(
                samples["client_id"], samples["request_id"], CountRenderTask(3)
            )
        )
        decoded = FieldCodec.decode(RenderCommand, encoded)
        self.assertEqual(decoded.task.execute(), 3)
        with self.assertRaises(ValueError):
            FieldCodec.decode(RenderCommand, {"type": "not_a_command"})

    async def test_each_reply_owns_its_transition_and_new_member(self):
        class QueuedReply(PendingReply):
            pass

        samples = dict(
            request_id=uuid4(), result=CapturedResult(9), error="worker error"
        )
        for member in RenderReply.members_with(RenderReply):
            with self.subTest(member=member):
                client = ReactionClient()
                submission = RenderSubmission(
                    samples["request_id"],
                    CountRenderTask(9),
                    asyncio.get_running_loop().create_future(),
                )
                reply = member(
                    **{
                        field.name: samples[field.name]
                        for field in fields(member)
                        if field.name in samples
                    }
                )
                if issubclass(member, CancelledReply):
                    with self.assertRaises(asyncio.CancelledError):
                        await reply.advance(submission, client)
                    self.assertEqual(client.acks, 1)
                elif issubclass(member, (FailedReply, UnknownReply, AcknowledgedReply)):
                    with self.assertRaises(RuntimeError):
                        await reply.advance(submission, client)
                    self.assertEqual(
                        client.acks,
                        int(
                            issubclass(member, FailedReply)
                            and not issubclass(member, RejectedReply)
                        ),
                    )
                else:
                    next_command = await reply.advance(submission, client)
                    if issubclass(member, CompleteReply):
                        self.assertIsNone(next_command)
                        self.assertEqual(submission.result.result(), 9)
                        self.assertEqual(client.acks, 1)
                    elif issubclass(member, BusyReply):
                        self.assertIsInstance(next_command, SubmitRender)
                    else:
                        self.assertIsInstance(next_command, PollRender)

        self.assertIs(RenderReply.decode("queued"), QueuedReply)

    def test_category_capabilities_and_new_member(self):
        class ReasoningCategory(AgentWork, MessageCategory):
            label = "Reasoning"

        for member in MessageCategory.members_with(MessageCategory):
            boundary = AgentActivityBoundary()
            if issubclass(member, AgentWork):
                self.assertTrue(boundary.observe(member))
                self.assertFalse(boundary.observe(member))
            elif issubclass(member, FromPerson):
                boundary._pending = False
                self.assertFalse(boundary.observe(member))
                self.assertTrue(boundary._pending)
            elif issubclass(member, FromAgent):
                self.assertFalse(boundary.observe(member))
                self.assertFalse(boundary._pending)
            else:
                self.assertFalse(boundary.observe(member))
                self.assertTrue(boundary._pending)
        self.assertIs(MessageCategory.decode("reasoning"), ReasoningCategory)
        self.assertIn(ReasoningCategory, all_categories())

    async def test_real_service_new_task_retention_isolation_and_release(self):
        service = RenderService(RenderServiceConfig(max_workers=1, max_pending=1))
        client, foreign, request = uuid4(), uuid4(), uuid4()
        try:
            self.assertIsInstance(
                SubmitRender(client, request, CountRenderTask(17)).execute(service),
                AcceptedReply,
            )
            self.assertIsInstance(
                SubmitRender(client, uuid4(), CountRenderTask(4)).execute(service),
                BusyReply,
            )
            self.assertIsInstance(
                PollRender(foreign, request).execute(service), UnknownReply
            )
            async with asyncio.timeout(10):
                reply = PollRender(client, request).execute(service)
                while isinstance(reply, PendingReply):
                    await asyncio.sleep(0.01)
                    reply = PollRender(client, request).execute(service)
            self.assertIsInstance(reply, CompleteReply)
            self.assertEqual(reply.result.value, 17)
            self.assertEqual(PollRender(client, request).execute(service), reply)
            self.assertEqual(service.pending_count, 1)
            AcknowledgeRender(client, request).execute(service)
            self.assertEqual(service.pending_count, 0)
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
