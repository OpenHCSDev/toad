"""Real large saved history, native Codex/ACP, and every painted summary frame."""

import asyncio
import hashlib
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, os.environ["CORE_FIXTURE_TESTS"])
from codex_loopback_provider import CodexLoopbackProvider, local_codex_key
from context_native_installed_pilot import InstalledApp
from l0a_native_installed_pilot import main, until
from saved_state_user_journey_pilot import submit_editor, click_tab

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
    cancel = "--cancel" in sys.argv
    source_session = app.selected_session
    source_digest = hashlib.sha256(Path(session).read_bytes()).hexdigest()

    async def tab_return():
        from toad.navigation_target import NavigationContext, channel_target
        project = agent.project_root_path
        user = comms.messaging.user_identity(str(project)).name
        await channel_target("#team").open(NavigationContext(app, app.selected_mode, project, user))
        await app.selected_session.wait_content_ready()
        await click_tab(app, pilot, source_session.id)
        assert app.selected_session is source_session
        assert app.selected_session.conversation is view

    await submit_editor(pilot, view.prompt.prompt_text_area,
                        "/goal One isolated summary continuation" if goal else "/compact")
    try:
        await until(pilot, partial_entered.is_set, 35)
        await until(pilot, lambda: any(f["partial"] and f["draft"] for f in frames), 25)
        await tab_return()
        await until(pilot, lambda: frames[-1]["partial"] and frames[-1]["draft"], 15)
        summaries = journal.summaries.history(session)
        assert len(summaries) == 1 and summaries[0].state.declared_name == "reserved"
        from agent_comms.turn_phase import CompactionPhase
        phase = comms.registry.require("beta").turn_state.phase
        assert isinstance(phase, CompactionPhase) and phase.source is not None
        assert not view.turns.owner.can_compact
        await submit_editor(pilot, view.prompt.prompt_text_area, "/compact")
        assert len(journal.summaries.history(session)) == 1
        await until(pilot, lambda: phase.source.label in "\n".join(
            strip.text for strip in app.screen._compositor.render_strips()), 10)
        progress = {"operation_id": phase.operation_id,
                    "source_bytes_done": phase.source.source_bytes_done,
                    "source_bytes_total": phase.source.source_bytes_total,
                    "label": phase.source.label, "elapsed_ms": phase.source.elapsed_ms}
        evidence = Path(os.environ["L0A_EVIDENCE"])
        (evidence / "provisional-progress.json").write_text(json.dumps(progress, indent=2))
        (evidence / "provisional.svg").write_text(app.export_screenshot())
        if cancel:
            # Original in-flight source publication predates the journal outcome.
            # It must not erase that later outcome, even though native bytes did
            # not change during cancellation.
            before_cancel = await agent.get_transcript_page()
            await pilot.press("escape", "escape")
            await until(pilot, lambda: not comms.registry.require("beta").executing, 30)
            partial_release.set()
            (evidence / "cancelled-before-end.svg").write_text(app.export_screenshot())
            view.window.focus(scroll_visible=False)
            await pilot.press("end")
            from agent_comms.compaction_outcomes import CompactionOutcomeTranscript
            outcome_page = await agent.get_transcript_page()
            outcomes = [event for event in outcome_page.events
                        if isinstance(event, CompactionOutcomeTranscript)]
            assert len(outcomes) == 1
            assert outcomes[0].identity == summaries[0].identity
            outcome_label = outcomes[0].text.split(".", 1)[0]
            await until(pilot, lambda: outcome_label in "\n".join(
                strip.text for strip in app.screen._compositor.render_strips()), 15)
            assert not before_cancel.after.contains(outcome_page.after)
            await view.transcript.snapshot(before_cancel)
            await until(pilot, lambda: not view.window.history_lock.locked(), 10)
            await tab_return()
            view.window.focus(scroll_visible=False)
            await pilot.press("end")
            await until(pilot, lambda: outcome_label in "\n".join(
                strip.text for strip in app.screen._compositor.render_strips()), 15)
            provider_posts = len(provider.requests)
            await agent.session.reconnect()
            await until(pilot, agent.session.settled.is_set, 30)
            assert agent.session.connected
            restored = await agent.get_transcript_page()
            restored_outcomes = [event for event in restored.events
                                 if isinstance(event, CompactionOutcomeTranscript)]
            assert len(restored_outcomes) == 1 and restored_outcomes[0] == outcomes[0]
            view.window.focus(scroll_visible=False)
            await pilot.press("end")
            await until(pilot, lambda: outcome_label in "\n".join(
                strip.text for strip in app.screen._compositor.render_strips()), 15)
            from toad.widgets.agent_response import AgentResponse
            notices = [block for block in view.query(AgentResponse)
                       if block.source == outcomes[0].text]
            assert len(notices) == 1, "Cancellation outcome presentation is not original/once"
            assert len(provider.requests) == provider_posts, "Source refresh replayed provider work"
            assert hashlib.sha256(Path(session).read_bytes()).hexdigest() == source_digest
            summaries = journal.summaries.history(session)
            assert len(summaries) == 1 and not isinstance(summaries[0].state,
                                                       (LinkedSummary, ManualCommittedSummary))
            originals = [row for row in InputDispositions(comms.root / InputDispositions.filename)
                         .read().rows.values() if row.key.startswith("turn:")]
            assert not originals and not goal_calls
            assert not any(frame["committed"] for frame in frames)
            receipt = {"mode": "cancel", "source_unchanged": True,
                       "partial_before_cancel": True, "canonical_progress_painted": True,
                       "summary_state": summaries[0].state.declared_name,
                       "originals": len(originals), "paid_requests": 0,
                       "original_outcome_once": True, "stale_snapshot_preserved": True,
                       "cancel_tab_return": True, "cancel_reconnect_once": True,
                       "operation_id": outcomes[0].identity.operation_id,
                       "provider_posts": len(provider.requests)}
            (evidence / "summary-receipt.json").write_text(json.dumps(receipt, indent=2))
            (evidence / "cancelled.svg").write_text(app.export_screenshot())
            (evidence / "semantic-frames.json").write_text(json.dumps(frames))
            return
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
        from toad.widgets.agent_response import AgentResponse
        from agent_comms.transcript_events import NoticeTranscript
        page = await agent.get_transcript_page()
        canonical = [event for event in page.events if isinstance(event, NoticeTranscript)
                     and event.text.startswith("## Context compacted")]
        assert len(canonical) == 1, "Compaction did not produce one original native summary"
        await until(pilot, lambda: any(history.committed_cursor.contains(page.after)
                    for history in view.window.histories if history.state.reports_coverage), 25)
        await until(pilot, lambda: not view.window.history_lock.locked(), 10)
        await pilot.pause(0.5)
        view.window.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        summaries_visible = [block for block in view.query(AgentResponse)
                             if block.source.startswith("## Context compacted")]
        census = {"canonical_summaries": len(canonical),
                  "registered_committed_headers": len(summaries_visible),
                  "provisional_streams": sum(block.source.startswith("## Compaction summary · draft")
                                             for block in view.query(AgentResponse)),
                  "histories": [{"state": type(history.state).__name__,
                                 "offset": history.committed_cursor.offset,
                                 "wire_seq": history.committed_cursor.wire_seq}
                                for history in view.window.histories],
                  "native_saved_bytes": Path(session).stat().st_size,
                  "backend_busy": comms.registry.require("beta").executing}
        evidence = Path(os.environ["L0A_EVIDENCE"])
        (evidence / "committed-census.json").write_text(json.dumps(census, indent=2))
        (evidence / "committed.svg").write_text(app.export_screenshot())
        assert len(summaries_visible) == 1, census
        assert census["provisional_streams"] == 0, census
        provider_posts = len(provider.requests)
        await tab_return()
        view.window.scroll_end(animate=False, immediate=True)
        await until(pilot, lambda: frames[-1]["partial"] and frames[-1]["committed"]
                    and not frames[-1]["draft"], 15)
        await agent.session.reconnect()
        await until(pilot, agent.session.settled.is_set, 30)
        assert agent.session.connected
        await until(pilot, lambda: any(history.committed_cursor.contains(page.after)
                    for history in view.window.histories if history.state.reports_coverage), 25)
        await until(pilot, lambda: not view.window.history_lock.locked(), 10)
        view.window.scroll_end(animate=False, immediate=True)
        await until(pilot, lambda: frames[-1]["partial"] and frames[-1]["committed"]
                    and not frames[-1]["draft"], 15)
        restored = [block for block in view.query(AgentResponse)
                    if block.source.startswith("## Context compacted")]
        assert len(restored) == 1, "Reconnect duplicated the committed summary"
        assert len(provider.requests) == provider_posts, "Display return requested provider input"
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
                   "partial_tab_return": True, "committed_tab_return": True,
                   "committed_reconnect_once": True,
                   "canonical_progress_painted": True,
                   "goal_originals": len(originals), "visible_frames": len(frames)}
        Path(os.environ["L0A_EVIDENCE"], "summary-receipt.json").write_text(json.dumps(receipt, indent=2))
        Path(os.environ["L0A_EVIDENCE"], "semantic-frames.json").write_text(json.dumps(frames))
        print(json.dumps(receipt), flush=True)
    finally:
        Path(os.environ["L0A_EVIDENCE"], "semantic-frames.json").write_text(json.dumps(frames))
        if cancel:
            from toad.widgets.agent_response import AgentResponse
            Path(os.environ["L0A_EVIDENCE"], "cancel-resource-census.json").write_text(
                json.dumps({"source_unchanged": hashlib.sha256(Path(session).read_bytes()).hexdigest()
                            == source_digest,
                            "notices": [block.source[:200] for block in view.query(AgentResponse)
                                        if block.source.startswith("## Compaction")],
                            "summary_states": [row.state.declared_name
                                               for row in journal.summaries.history(session)]}, indent=2))
            Path(os.environ["L0A_EVIDENCE"], "cancel-final.svg").write_text(app.export_screenshot())
        partial_release.set()
        answer_release.set()


if __name__ == "__main__":
    with CodexLoopbackProvider(response_factory=response, after_chunk=hold) as provider:
        asyncio.run(main(app_type=StreamApp, acceptance=acceptance, prepare_state=prepare,
                        fixture_stage=Path(os.environ["COMPACTION_FIXTURE_STAGE"])
                            if "COMPACTION_FIXTURE_STAGE" in os.environ else None,
                        native_settings={"transport": "sse", "retry": {"enabled": False},
                            "compaction": {"enabled": True, "reserveTokens": 16384, "keepRecentTokens": 20000}}))
