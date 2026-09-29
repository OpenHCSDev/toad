"""Independently generated native histories, real Linux writer, ordinary GC.

Uses the existing localhost Pi/ACP and normal App/Pilot fixtures. Run only under
an actual PTY; no provider, history, process, renderer or writer is substituted.
"""
import asyncio
import json
import os
from pathlib import Path
import statistics
import threading
from dataclasses import fields
from collections import Counter
from agent_comms.transcripts import Transcripts
from agent_comms.field_codec import FieldCodec
from weakref import ref

import psutil
from acp.schema import TextContentBlock
from agent_comms.acp import CommsClient
from agent_comms.threads import Thread
from native_session_retention_pilot import PaintedSwitchApp, conversation_paint, physical_painted_switch
from l0a_native_installed_pilot import main as native_fixture, until
from saved_state_user_journey_pilot import SavedStateSubscriber
from viewport_recent_tabs_pilot import settled
from toad.navigation_target import ThreadTarget
from toad.widgets.prepared_markdown import PreparedConversationMarkdown


COHORTS = (int(os.environ.get("WORKSPACE_LOADED_COHORTS", "4")),)
NAMES = ("beta", *(f"loaded-{index}" for index in range(1, max(COHORTS))))


_read_identities = {}
_read_changes = []
_read_lock = threading.Lock()


def capture_read_identity(frame, event, result):
    if frame.f_code is not Transcripts.capture_page_read.__code__ or event != "return" or result is None:
        return
    identity = result.identity
    with _read_lock:
        previous = _read_identities.get(identity.requested_name)
        _read_identities[identity.requested_name] = identity
        if previous is not None and previous != identity:
            changes = {field.name: [FieldCodec.encode(getattr(previous, field.name)),
                                   FieldCodec.encode(getattr(identity, field.name))]
                       for field in fields(identity)
                       if getattr(previous, field.name) != getattr(identity, field.name)}
            if previous.thread != identity.thread:
                changes["thread"] = {field.name: [FieldCodec.encode(getattr(previous.thread, field.name)),
                    FieldCodec.encode(getattr(identity.thread, field.name))]
                    for field in fields(identity.thread)
                    if getattr(previous.thread, field.name) != getattr(identity.thread, field.name)}
            _read_changes.append({"name": identity.requested_name, "changes": changes})


def reply(request, number):
    marker = f"NATIVE_COHORT_REPLY_{number}"
    text = "\n\n".join(f"{marker} paragraph {index}: independently generated actual native history with stable reader content." for index in range(40))
    return {"role": "assistant", "content": text}, "stop"


async def prepare(comms, project, requests, entered, release, hold_next):
    release.set()
    client = CommsClient(comms, runtime_enabled=True,
        private_nk_native_package=Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]),
        private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"])
    observer = SavedStateSubscriber()
    client.on_connect(observer)
    try:
        for name in NAMES:
            if name != "beta":
                comms.registry.declare(Thread(name, frozenset({"team"}), str(project),
                    model="selected-offline/fixture", thinking_level="off"))
            # Fail before admission rather than exhausting the owner's machine.
            # This is test resource protection, not a production cache cap.
            assert psutil.virtual_memory().available > psutil.virtual_memory().total / 4
            await client.load_session(cwd=str(project), session_id=name)
            await client.prompt(name, [TextContentBlock(type="text", text=f"INDEPENDENT_NATIVE_HISTORY_{name}")])
            observer.require_success()
        files = {comms.registry.require(name).session_file for name in NAMES}
        assert len(files) == len(NAMES) and None not in files
        assert len(requests) == len(NAMES)
    finally:
        await client.shutdown()


async def continuous_acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    assert type(app._driver).__name__ == "LinuxDriver", "Writer proof requires the real terminal driver"
    workspace = app.screen
    sources, checkpoints = [], {}
    native_bytes = {name: Path(comms.registry.require(name).session_file).read_bytes() for name in NAMES}
    for index, name in enumerate(NAMES):
        if index:
            await ThreadTarget(name).open(app.selected_session.navigation_context)
        source = app.selected_session
        marker = f"NATIVE_COHORT_REPLY_{index + 1}"
        await until(pilot, lambda: marker in conversation_paint(app.screen))
        view = source.conversation
        await settled(pilot, view)
        editor = view.prompt.prompt_text_area
        editor.insert(f"{name}_UNSENT_DRAFT")
        editor.history.checkpoint()
        editor.insert(" WITH_UNDO")
        await pilot.pause()
        leaves = tuple(ref(body) for body in view.query(PreparedConversationMarkdown)
                       if body in workspace._compositor.visible_widgets and body.region.overlaps(view.window.scrollable_content_region))
        assert leaves, "Native loaded source requires visible real message bodies"
        sources.append(source)
        checkpoints[source.id] = (view.agent, view.agent.process.process, editor.document,
            editor.history, editor.text, marker, leaves, comms.registry.require(name).process_identity)
    records = []
    for count in COHORTS:
        cohort = sources[:count]
        reads_before = app.coordination_access.service.transcripts.page_reads
        timings = []
        for order in (tuple(reversed(cohort)), tuple(cohort), tuple(reversed(cohort))):
            for source in order:
                if source is app.selected_session:
                    continue
                original_agent, process, document, history, draft, marker, leaves, owner = checkpoints[source.id]
                timing = await physical_painted_switch(app, pilot, source.id, (draft, marker))
                view = app.selected_session.conversation
                editor = view.prompt.prompt_text_area
                assert app.screen is workspace
                assert view.agent is original_agent and original_agent.process.process is process
                assert process.returncode is None
                assert editor.document is document and editor.history is history and editor.text == draft
                assert all(body() in workspace._compositor.visible_widgets for body in leaves)
                assert comms.registry.require(source._comms_thread).process_identity == owner
                timings.append({"source": source._comms_thread, **timing})
        reads_after = app.coordination_access.service.transcripts.page_reads
        Path(os.environ["NATIVE_RETENTION_RECEIPT"]).with_suffix(".identity.json").write_text(json.dumps(_read_changes, indent=2))
        assert reads_before == reads_after, (reads_before, reads_after)
        assert len(requests) == len(NAMES), "Navigation replayed native input"
        assert app.preparation.retained_bytes <= app.preparation.max_bytes
        assert all(Path(comms.registry.require(name).session_file).read_bytes() == native_bytes[name] for name in NAMES)
        record = {"loaded_histories": count, "distinct_native_files": len(native_bytes),
            "compositor_median_ms": statistics.median(row["first_paint_ms"] for row in timings),
            "writer_median_ms": statistics.median(row["first_written_ms"] for row in timings),
            "writer_max_ms": max(row["last_observed_written_ms"] for row in timings),
            "raw_page_reads": reads_after - reads_before, "prepared_bytes": app.preparation.retained_bytes,
            "ui_rss_bytes": psutil.Process().memory_info().rss, "switches": timings}
        records.append(record)
        Path(os.environ["NATIVE_RETENTION_RECEIPT"]).write_text(json.dumps(records, indent=2))
    print("INDEPENDENT_LOADED_NATIVE_WRITER_RETURN_CUSTODY_PASS", flush=True)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    try:
        await continuous_acceptance(app, pilot, agent, comms, entered, release, hold_next, requests)
    finally:
        Path(os.environ["NATIVE_RETENTION_RECEIPT"]).with_suffix(".identity.json").write_text(json.dumps(_read_changes, indent=2))
        runtime = app.preparation
        Path(os.environ["NATIVE_RETENTION_RECEIPT"]).with_suffix(".retention.json").write_text(json.dumps({
            "entries": len(runtime._ready), "entry_limit": runtime.max_entries,
            "retained_bytes": runtime.retained_bytes, "byte_limit": runtime.max_bytes,
            "kinds": dict(Counter(key.kind.__name__ for key in runtime._ready)),
            "page_reads": app.coordination_access.service.transcripts.page_reads,
        }, indent=2))


if __name__ == "__main__":
    if os.environ.get("NATIVE_SOURCE_IDENTITY_CENSUS"):
        threading.setprofile_all_threads(capture_read_identity)
    asyncio.run(native_fixture(app_type=PaintedSwitchApp, prepare_state=prepare,
        provider_reply=reply, acceptance=acceptance, headless=False))
