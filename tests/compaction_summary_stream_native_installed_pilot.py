"""Real large saved history, native Codex/ACP, and every painted summary frame."""

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, os.environ["CORE_FIXTURE_TESTS"])
from codex_loopback_provider import CodexLoopbackProvider, local_codex_key
from context_native_installed_pilot import InstalledApp
from l0a_native_installed_pilot import main, until
from saved_state_user_journey_pilot import submit_editor

PARTIAL = "PROGRESSIVE_COMPACTION_SUMMARY"
SUMMARY = PARTIAL + ": retained decisions and evidence; final continuation context."
ANSWER = "ONE_AUTOMATIC_GOAL_ANSWER"
partial_entered, partial_release = threading.Event(), threading.Event()
answer_entered, answer_release = threading.Event(), threading.Event()
summary_hold_claimed = threading.Event()
goal_calls = []
frames = []


class StreamApp(InstalledApp):
    def _display(self, *args, **kwargs):
        result = super()._display(*args, **kwargs)
        frame = "\n".join(strip.text for strip in self.screen._compositor.render_strips())
        # Private history never leaves the scratch run. Only semantic flags do.
        frames.append({"partial": PARTIAL in frame, "draft": "Compaction summary · draft" in frame,
                       "committed": "Context compacted" in frame, "answer": ANSWER in frame})
        return result


def response(request, number):
    from agent_comms.goal_scheduler import GOAL_CONTINUE_PROMPT
    if number <= 2:
        size = 538709 + 164741 if number == 1 else 64
        return ("CONTROLLED_RETAINED_HISTORY " * (size // 28 + 1))[:size], 20, 0
    if GOAL_CONTINUE_PROMPT in json.dumps(request["input"][-1]):
        goal_calls.append(number)
        return ANSWER, 10, 0
    return SUMMARY, 20, 12000


def hold(request, number, index):
    if number in goal_calls and index == 1:
        answer_entered.set()
        assert answer_release.wait(35), "UI did not release autonomous response"
    # Hold a synthesis stream after a visible prefix, before terminal usage.
    if (index == 5 and "<segment-summary" in json.dumps(request["input"])
            and not summary_hold_claimed.is_set()):
        summary_hold_claimed.set()
        partial_entered.set()
        assert partial_release.wait(35), "UI did not paint the provisional summary"


async def prepare(comms, project, *_args):
    from acp.schema import TextContentBlock
    from agent_comms.acp import CommsClient
    from saved_state_user_journey_pilot import SavedStateSubscriber
    config = Path(os.environ["PI_CODING_AGENT_DIR"])
    (config / "models.json").write_text(json.dumps({"providers": {"selected-offline": {
        "api": "openai-codex-responses", "baseUrl": provider.base_url,
        "models": [{"id": "fixture", "name": "Offline Codex", "contextWindow": 512000,
                    "maxTokens": 128000, "reasoning": True}],
    }}}))
    (config / "auth.json").write_text(json.dumps({"selected-offline": {
        "type": "api_key", "key": local_codex_key()}}))
    subscriber = SavedStateSubscriber()
    client = CommsClient(comms, runtime_enabled=True,
        private_nk_native_package=Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]),
        private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"])
    client.on_connect(subscriber)
    provider.chunk_characters = 8192
    provider.input_tokens = 399443
    try:
        await client.load_session(cwd=str(project), session_id="beta")
        for text in ("ISOLATED_OLDER_CONTEXT", "ISOLATED_RECENT_CONTEXT"):
            async with asyncio.timeout(35):
                await client.prompt("beta", [TextContentBlock(type="text", text=text)])
            subscriber.require_success()
    finally:
        await client.shutdown()
        await asyncio.to_thread(comms.owners.stop, "beta")
    provider.chunk_characters = 8
    provider.input_tokens = 100
    models = json.loads((config / "models.json").read_text())
    models["providers"]["selected-offline"]["models"][0]["contextWindow"] = 272000
    (config / "models.json").write_text(json.dumps(models))
    await asyncio.to_thread(comms.owners.start, "beta")


async def acceptance(app, pilot, agent, comms, *_args):
    from agent_comms.compaction_journal import CompactionJournal
    from agent_comms.compaction_states import LinkedSummary, ManualCommittedSummary
    from agent_comms.input_disposition import InputDispositions
    view = app.selected_session.conversation
    await until(pilot, lambda: view.agent_ready, 35)
    assert len(provider.requests) == 2, "Saved history attachment invoked the provider"
    session = comms.registry.require("beta").session_file
    saved_bytes = Path(session).stat().st_size
    journal = CompactionJournal(comms.root / "compaction-commits.sqlite3")
    goal = "--goal" in sys.argv
    await submit_editor(pilot, view.prompt.prompt_text_area,
                        "/goal One isolated summary continuation" if goal else "/compact")
    try:
        await until(pilot, partial_entered.is_set, 35)
        await until(pilot, lambda: any(f["partial"] and f["draft"] for f in frames), 25)
        summaries = journal.summaries.history(session)
        assert len(summaries) == 1 and summaries[0].state.declared_name == "reserved"
        partial_release.set()
        if goal:
            await until(pilot, answer_entered.is_set, 35)
            await until(pilot, lambda: any(f["partial"] and f["committed"] and not f["draft"] for f in frames), 25)
            assert await pilot.click("#goal-toggle")
            await until(pilot, lambda: comms.registry.require("beta").goal.state.declared_name == "paused")
            answer_release.set()
            await until(pilot, lambda: any(f["answer"] for f in frames), 25)
        await until(pilot, lambda: not comms.registry.require("beta").executing, 30)
        await until(pilot, lambda: any(f["partial"] and f["committed"] and not f["draft"] for f in frames), 25)
        rows = InputDispositions(comms.root / InputDispositions.filename).read().rows.values()
        originals = [row for row in rows if row.key.startswith("turn:")]
        assert len(originals) == (1 if goal else 0)
        assert len(goal_calls) == (1 if goal else 0)
        assert type(journal.summaries.history(session)[0].state) is (
            LinkedSummary if goal else ManualCommittedSummary)
        assert not provider.failures, provider.failures
        receipt = {"mode": "goal" if goal else "manual", "saved_bytes": saved_bytes,
                   "provider_posts": len(provider.requests), "partial_before_commit": True,
                   "immediate_committed_summary": True, "followup_inputs": 0,
                   "goal_originals": len(originals), "visible_frames": len(frames)}
        Path(os.environ["L0A_EVIDENCE"], "summary-receipt.json").write_text(json.dumps(receipt, indent=2))
        Path(os.environ["L0A_EVIDENCE"], "semantic-frames.json").write_text(json.dumps(frames))
        print(json.dumps(receipt), flush=True)
    finally:
        partial_release.set()
        answer_release.set()


if __name__ == "__main__":
    with CodexLoopbackProvider(response_factory=response, after_chunk=hold) as provider:
        asyncio.run(main(app_type=StreamApp, acceptance=acceptance, prepare_state=prepare,
                        native_settings={"transport": "sse", "retry": {"enabled": False},
                            "compaction": {"enabled": True, "reserveTokens": 16384, "keepRecentTokens": 20000}}))
