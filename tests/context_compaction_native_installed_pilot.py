"""Continuous native saved context -> real adaptive summary -> painted reply."""
import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from context_native_installed_pilot import InstalledApp
from l0a_native_installed_pilot import main, until, response_painted
from toad import messages


def usage(request, count):
    used = 31000 if count == 2 else 100
    return {"prompt_tokens": used, "completion_tokens": 10, "total_tokens": used + 10}


def paint(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    for index in (1, 2):
        await view.submit_input(messages.UserInputSubmitted(
            f"SAVED_CONTEXT_{index} " + "retained sample " * 400))
        await until(pilot, lambda: response_painted(app, view, f"NATIVE_RESPONSE_{index}"), 30)
        await until(pilot, lambda: not comms.registry.require("beta").executing)
    assert agent.context_measurement.available and agent.context_measurement.used >= 31000
    await agent.session.reconnect()
    await until(pilot, agent.session.settled.is_set)
    await until(pilot, lambda: "last response" in paint(app))
    assert len(requests) == 2, "Saved context reopen must not prompt provider"
    original_details = app.session_tracker.get_session(app.selected_mode)
    entered.clear()
    release.clear()
    hold_next.set()
    await view.submit_input(messages.UserInputSubmitted("COMPACT_AND_REPLY_ONCE"))
    try:
        assert await asyncio.to_thread(entered.wait, 20), "Real summary did not reach loopback"
        await until(pilot, lambda: "Compacting context" in paint(app), 20)
        assert original_details.state == "busy"
        Path("evidence/context-measurement/compacting-native.svg").write_text(app.export_screenshot())
        release.set()
        await until(pilot, lambda: response_painted(app, view, "COMPACTION_FINAL_ANSWER"), 30)
        assert app.session_tracker.get_session(app.selected_mode) is original_details
        assert sum("COMPACT_AND_REPLY_ONCE" in json.dumps(request["messages"])
                   for request in requests) == 1
        from agent_comms.transcript_events import UserTranscript
        assert sum(isinstance(e, UserTranscript) and e.text == "COMPACT_AND_REPLY_ONCE"
                   for e in comms.transcripts.thread_transcript("beta")) == 1
        print("PHYSICAL_NATIVE_SAVED_CONTEXT_ADAPTIVE_PHASE_PAINT_ONE_REPLY", flush=True)
    finally:
        release.set()


def reply(request, count):
    text = ("COMPACTION_FINAL_ANSWER" if "COMPACT_AND_REPLY_ONCE" in json.dumps(request["messages"])
            else f"NATIVE_RESPONSE_{count}")
    return {"role": "assistant", "content": text}, "stop"


goal_started, goal_release = threading.Event(), threading.Event()
goal_requests = set()
SAVED_ANSWER = "COLD_RETAINED_LONG_ANSWER history for the saved reader.\n" * 1000
SUMMARY = "COLD_GOAL_COMPACTION_SUMMARY: retained history was summarized once."
GOAL_ANSWER = "COLD_GOAL_CONTINUATION_ANSWER"


def goal_reply(request, count):
    from agent_comms.goal_scheduler import GOAL_CONTINUE_PROMPT
    if count <= 2:
        text = SAVED_ANSWER if count == 1 else "COLD_RECENT_ANSWER"
    elif GOAL_CONTINUE_PROMPT in json.dumps(request["messages"][-1]):
        goal_requests.add(count)
        text = GOAL_ANSWER
    else:
        text = SUMMARY
    Path(os.environ["L0A_EVIDENCE"], "provider-progress.json").write_text(json.dumps({
        "request_count": count, "goal_requests": sorted(goal_requests),
        "last_request_model": request.get("model"), "last_request_max_tokens": request.get("max_tokens"),
        "last_message": json.dumps(request["messages"][-1])[-500:],
    }, indent=2))
    return {"role": "assistant", "content": text}, "stop"


def hold_goal_response(request_number, index):
    if request_number in goal_requests and index == 0:
        goal_started.set()
        assert goal_release.wait(20), "UI did not release the goal response"


def goal_usage(request, count):
    used = 0 if count <= 2 else 100
    return {"prompt_tokens": used, "completion_tokens": 0, "total_tokens": used}


async def prepare_cold_goal(comms, project, requests, entered, release, hold_next):
    from acp.schema import TextContentBlock
    from agent_comms.acp import CommsClient
    from saved_state_user_journey_pilot import SavedStateSubscriber
    subscriber = SavedStateSubscriber()
    client = CommsClient(
        comms, runtime_enabled=True,
        private_nk_native_package=Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]),
        private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"],
    )
    client.on_connect(subscriber)
    release.set()
    hold_next.clear()
    try:
        await client.load_session(cwd=str(project), session_id="beta")
        for text in ("COLD_OLDER_QUESTION", "COLD_RECENT_QUESTION"):
            async with asyncio.timeout(25):
                await client.prompt("beta", [TextContentBlock(type="text", text=text)])
            subscriber.require_success()
    finally:
        await client.shutdown()
        await asyncio.to_thread(comms.owners.stop, "beta")
    assert len(requests) == 2
    session = Path(comms.registry.require("beta").session_file)
    assert "COLD_RETAINED_LONG_ANSWER" in session.read_text() and session.stat().st_size > 50000
    config = Path(os.environ["PI_CODING_AGENT_DIR"])
    models = json.loads((config / "models.json").read_text())
    selected = models["providers"]["selected-offline"]["models"][0]
    selected.update(contextWindow=10000, maxTokens=1000)
    (config / "models.json").write_text(json.dumps(models))
    await asyncio.to_thread(comms.owners.start, "beta")
    # Reopen this real saved context cold under the smaller selected model.
    # The usage remains low; native stored-context admission must decide.
    entered.clear()
    release.clear()
    hold_next.set()


async def goal_acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    from agent_comms.compaction_journal import CompactionJournal
    from agent_comms.compaction_states import LinkedSummary
    from agent_comms.input_disposition import InputDispositions
    from saved_state_user_journey_pilot import submit_editor
    evidence = Path(os.environ["L0A_EVIDENCE"])
    view = app.selected_session.conversation
    session = Path(comms.registry.require("beta").session_file)
    history = session.read_bytes()
    await until(pilot, lambda: view.agent_ready)
    assert len(requests) == 2, "Cold saved-history attachment called the provider"
    await submit_editor(pilot, view.prompt.prompt_text_area,
                        "/goal One automatic cold-context continuation")
    try:
        await until(pilot, entered.is_set, 25)
        await until(pilot, lambda: "Compacting context" in paint(app), 20)
        (evidence / "goal-compacting.txt").write_text(paint(app))
        (evidence / "goal-compacting.svg").write_text(app.export_screenshot())
        release.set()
        await until(pilot, goal_started.is_set, 30)
        await until(pilot, lambda: SUMMARY in paint(app), 20)
        (evidence / "goal-summary.txt").write_text(paint(app))
        # Pause through the actual UI after native has started the single goal
        # input. Pause governs the next continuation and preserves this answer.
        assert await pilot.click("#goal-toggle")
        await until(pilot, lambda: comms.registry.require("beta").goal.state.declared_name == "paused")
        goal_release.set()
        await until(pilot, lambda: not comms.registry.require("beta").executing)
        await until(pilot, lambda: GOAL_ANSWER in paint(app), 20)
        assert len(goal_requests) == 1, "Autonomous goal input repeated"
        rows = InputDispositions(comms.root / InputDispositions.filename).read()
        originals = [row for row in rows.rows.values() if row.key.startswith("turn:")]
        assert len(originals) == 1 and originals[0].has_started
        entries = [json.loads(line) for line in session.read_text().splitlines()]
        compact = [i for i, row in enumerate(entries) if row["type"] == "compaction"]
        started = [i for i, row in enumerate(entries)
                   if row.get("message", {}).get("inputId") == originals[0].native_id]
        assert len(compact) == len(started) == 1 and compact[0] < started[0]
        assert session.read_bytes().startswith(history), "Saved history was replaced"
        journal = CompactionJournal(comms.root / "compaction-commits.sqlite3")
        summaries = journal.summaries.history(str(session))
        assert len(summaries) == 1 and isinstance(summaries[0].state, LinkedSummary)
        assert not journal.publications.pending(str(session))
        assert "Internal error" not in paint(app)
        (evidence / "goal-answer.txt").write_text(paint(app))
        (evidence / "goal-receipt.json").write_text(json.dumps({
            "cold_saved_bytes": len(history), "selected_model_window": 10000,
            "provider_posts": len(requests), "goal_inputs": len(originals),
            "compactions": len(compact), "compaction_before_goal": True,
            "goal_input": originals[0].public(), "summary": summaries[0].state.declared_name,
        }, indent=2))
    finally:
        release.set()
        goal_release.set()


if __name__ == "__main__":
    if "--goal" in sys.argv:
        asyncio.run(main(app_type=InstalledApp, acceptance=goal_acceptance,
                        prepare_state=prepare_cold_goal, provider_reply=goal_reply,
                        provider_usage=goal_usage,
                        provider_after_chunk=hold_goal_response, provider_request_budget=40,
                        native_settings={"compaction": {
                            "enabled": True, "reserveTokens": 1000, "keepRecentTokens": 100},
                            "retry": {"enabled": False}}))
    else:
        asyncio.run(main(app_type=InstalledApp, acceptance=acceptance, provider_usage=usage,
                        provider_reply=reply, native_settings={"compaction": {
                            "enabled": True, "reserveTokens": 4096, "keepRecentTokens": 1024}}))
