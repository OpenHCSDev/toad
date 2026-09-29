"""Continuous native saved context -> real adaptive summary -> painted reply."""
import asyncio
import json
import os
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
    await agent.reconnect()
    await until(pilot, agent.session_ready_event.is_set)
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


if __name__ == "__main__":
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance, provider_usage=usage,
                    provider_reply=reply, native_settings={"compaction": {
                        "enabled": True, "reserveTokens": 4096, "keepRecentTokens": 1024}}))
