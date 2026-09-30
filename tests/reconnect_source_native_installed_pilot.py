"""Actual native replies and source reconnect, including distinct equal bodies."""
import asyncio
from importlib.resources import files
from importlib.metadata import distribution
import json
import os
from pathlib import Path

from agent_comms.transcript_events import AssistantTranscript, UserTranscript
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory
from runtime_fixture import ToadApp
from l0a_native_installed_pilot import main, until, response_painted


BODY = "ORIGINAL_EQUAL_NATIVE_REPLY"


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")

    async def on_load(self):
        from toad.setting_choices import ThemeChoice
        self.settings.ui.theme = ThemeChoice.decode("textual-dark")
        await super().on_load()


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    root = Path(os.environ["L0A_EVIDENCE"])
    view = app.selected_session.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    process = comms.registry.require("beta").process_identity
    receipt = {"provider": "localhost-only", "paid_calls": 0, "phases": [],
               "installed": {name: distribution(name).read_text("direct_url.json")
                             for name in ("batrachian-toad", "agent-comms", "textual")}}

    async def observe(label, expected):
        await until(pilot, lambda: response_painted(app, view, BODY))
        page = await agent.get_transcript_page()
        if label.startswith("reconnect"):
            await until(pilot, lambda: not view.window.history_lock.locked() and any(
                history.committed_cursor == page.after for history in view.window.histories
                if history.is_attached and history.state.reports_coverage))
            await pilot.pause()
        source = [event for event in page.events if isinstance(event, AssistantTranscript)]
        users = [event for event in page.events if isinstance(event, UserTranscript)]
        widgets = tuple(block for block in view.query(AgentResponse) if block.source == BODY)
        window = view.window.region
        paint = "\n".join(strip.crop(window.x, window.right).text for strip in
                          app.screen._compositor.render_strips()[window.y:window.bottom])
        phase = {"phase": label, "canonical_assistants": len(source),
                 "canonical_users": [event.native_id for event in users],
                 "source_file": page.after.session_file, "source_offset": page.after.offset,
                 "registered_response_resources": len(widgets),
                 "resource_ids": [id(block) for block in widgets],
                 "painted_bodies": paint.count(BODY), "painted_headers": paint.count("Agent ·"),
                 "histories": [{"resource": id(history), "registered": history in view.window.histories,
                                 "source": history.committed_cursor.session_file,
                                 "offset": history.committed_cursor.offset}
                                for history in view.query(TranscriptHistory)],
                 "provider_requests": len(requests)}
        receipt["phases"].append(phase)
        (root / "reconnect-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        app.save_screenshot(str(root / (label + ".svg")))
        print("RECONNECT_PHASE", json.dumps(phase), flush=True)
        assert len(source) == expected and all(event.text == BODY for event in source), phase
        assert len(users) == expected and len({event.native_id for event in users}) == expected, phase
        assert len(widgets) == expected and paint.count(BODY) == expected, phase
        assert paint.count("Agent ·") == expected, phase
        assert comms.registry.require("beta").process_identity == process
        assert len(requests) == expected

    for number in (1, 2):
        view.prompt.text = f"DISTINCT_ORIGINAL_INPUT_{number}"
        view.prompt.prompt_text_area.focus()
        await pilot.press("enter")
        await until(pilot, lambda: len(requests) == number)
        await until(pilot, lambda: not comms.registry.require("beta").executing)
        await observe(f"answer-{number}", number)
        await agent.session.reconnect()
        await until(pilot, agent.session.settled.is_set)
        await until(pilot, lambda: view.agent_ready)
        await observe(f"reconnect-{number}", number)
    assert app._exception is None
    receipt["complete"] = True
    (root / "reconnect-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance,
                     provider_reply=lambda request, number: ({"role": "assistant", "content": BODY}, "stop"),
                     provider_request_budget=2, fixture_stage=Path(os.environ["RECONNECT_FIXTURE_STAGE"])))
