"""One cold saved-owner context disclosure in the original installed terminal.

The retained launch config stays in RAM. The existing SDK fork and private
protocol root are borrowed; no new fork, native input or priming RPC is made.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import shlex
import sys
import time


def load_recorder():
    recorder_path = Path(__file__).parent / "tools/record_installed_tui.py"
    spec = importlib.util.spec_from_file_location("cold_context_recorder", recorder_path)
    recorder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = recorder
    spec.loader.exec_module(recorder)

    class ColdContextJourney(recorder.PhysicalJourney):
        scope = "Saved history/roster and cold native context Tree before any prompt"

        @classmethod
        def script(cls, args):
            mark = recorder.marker_command()
            helper = Path(__file__).resolve().parents[1] / "tools/performance/click_history.py"
            def click(state, target, name=None, button=1):
                return "exec --sync " + shlex.join((sys.executable, str(helper),
                    "--state", state, "--target", target,
                    *(() if name is None else ("--name", name)), "--button", str(button)))
            def select(state, kind):
                return "exec --sync " + shlex.join((sys.executable, str(Path(__file__).resolve()),
                    "--select-context", state, kind))
            if os.environ.get("TOAD_RECORDED_CONTEXT_AUDIT") == "1":
                def selected(phase, field):
                    # Reveal by the original materialized Tree line, then acquire
                    # fresh clipped geometry before the actual pointer selection.
                    member = field.removeprefix("TOAD_RECORDED_").removesuffix("_NODE").lower()
                    revealed = "revealed-" + phase + "-" + member
                    focused = "focused-" + phase + "-" + member
                    return "\n".join((
                        # Native focus traversal from the declared search Input
                        # passes Search / Read full / Copy before Tree. Clicking
                        # the Tree's center selects/toggles an unrelated row.
                        click("phase-" + phase + "-state.pickle", "widget", "Input#context-search"),
                        "key --repeat 4 --repeat-delay 5 Tab",
                        mark + focused,
                        "exec --sync " + shlex.join((sys.executable, str(Path(__file__).resolve()),
                            "--reveal-context", "phase-" + focused + "-state.pickle", os.environ[field])),
                        "sleep .2", mark + revealed,
                        select("phase-" + revealed + "-state.pickle", "exact:" + os.environ[field])))
                export = os.environ["TOAD_CONTEXT_AUDIT_EXPORT"]
                return "\n".join((
                    mark + "saved --wait-history-seconds 12 --wait-history-thread configured-source",
                    "key ctrl+b", "sleep 1", mark + "roster",
                    click("phase-roster-state.pickle", "right_sidebar"),
                    "sleep 7", mark + "context-open",
                    click("phase-context-open-state.pickle", "context_tree"),
                    "key End space End", "sleep 1", mark + "recorded-request",
                    selected("recorded-request", "TOAD_RECORDED_REQUEST_NODE"),
                    "sleep 1", mark + "request-members",
                    selected("request-members", "TOAD_RECORDED_SYSTEM_NODE"),
                    "sleep 2", mark + "recorded-system",
                    click("phase-recorded-system-state.pickle", "widget", "Input#context-search"),
                    "type --clearmodifiers 'One fact'", "key Return", "sleep 2", mark + "recorded-search",
                    selected("recorded-search", "TOAD_RECORDED_SYSTEM_NODE"),
                    "sleep 1", mark + "recorded-result",
                    click("phase-recorded-result-state.pickle", "widget", "Button#context-read-full"),
                    "sleep 1", mark + "recorded-full", "key Escape", "sleep 1", mark + "recorded-return",
                    click("phase-recorded-return-state.pickle", "widget", "Button#context-copy"),
                    click("phase-recorded-return-state.pickle", "widget", "Input#context-export-path"),
                    "type --clearmodifiers " + shlex.quote(export), mark + "recorded-export-path",
                    click("phase-recorded-export-path-state.pickle", "widget", "Button#context-export"),
                    "sleep 1", mark + "recorded-export",
                    click("phase-recorded-export-state.pickle", "widget", "Input#context-search"),
                    "key Home shift+End BackSpace", "key Return", "sleep 1", mark + "tree-restored",
                    selected("tree-restored", "TOAD_RECORDED_TRANSCRIPT_NODE"),
                    "sleep 1", mark + "transcript-expanded",
                    "exec --sync " + shlex.join((sys.executable, str(Path(__file__).resolve()),
                        "--reveal-context", "phase-transcript-expanded-state.pickle",
                        os.environ["TOAD_RECORDED_COORDINATION_NODE"].rsplit('/contributor/',1)[0])),
                    "key space", "sleep 1", mark + "contributor-expanded",
                    "exec --sync " + shlex.join((sys.executable, str(Path(__file__).resolve()),
                        "--reveal-context", "phase-contributor-expanded-state.pickle",
                        os.environ["TOAD_RECORDED_COORDINATION_NODE"])),
                    "sleep 2", mark + "exact-contributor",
                    selected("exact-contributor", "TOAD_RECORDED_COORDINATION_NODE"),
                    "sleep 2", mark + "recorded-coordination",
                    click("phase-recorded-coordination-state.pickle", "right_sidebar"),
                    "sleep 1", mark + "menus-ready",
                    click("phase-menus-ready-state.pickle", "thread", "configured-source", 3),
                    "sleep 1", mark + "thread-menu",
                    click("phase-thread-menu-state.pickle", "menu_action", "thread-tags"),
                    "sleep 1", mark + "thread-tags-form",
                    click("phase-thread-tags-form-state.pickle", "widget", "Input#command-field-tags"),
                    "key Home shift+End BackSpace", "type --clearmodifiers " + shlex.quote(os.environ["TOAD_CONTEXT_AUDIT_TAGS"]),
                    mark + "thread-tags-review",
                    click("phase-thread-tags-review-state.pickle", "widget", "Button#command-apply"),
                    "sleep 2", mark + "tag-applied",
                    click("phase-tag-applied-state.pickle", "channel", "#review417", 3),
                    "sleep 1", mark + "tag-menu",
                    click("phase-tag-menu-state.pickle", "menu_action", "rename-tag"),
                    "sleep 1", mark + "rename-form",
                    click("phase-rename-form-state.pickle", "widget", "Input#command-field-new-name"),
                    "key Home shift+End BackSpace", "type --clearmodifiers review417-renamed",
                    mark + "rename-review",
                    click("phase-rename-review-state.pickle", "widget", "Button#command-apply"),
                    "sleep 2", mark + "renamed",
                    click("phase-renamed-state.pickle", "channel", "#review417-renamed"),
                    "sleep 2", mark + "channel-open",
                    click("phase-channel-open-state.pickle", "editor"),
                    "type --clearmodifiers '/pin-channel '", "key Return", "sleep 2", mark + "slash-executed",
                    click("phase-slash-executed-state.pickle", "channel", "#review417-renamed", 3),
                    "sleep 1", mark + "delete-menu",
                    click("phase-delete-menu-state.pickle", "menu_action", "delete-tag"),
                    "sleep 1", mark + "delete-review",
                    click("phase-delete-review-state.pickle", "widget", "Button#command-apply"),
                    "sleep 2", mark + "deleted", "",
                ))
            query = os.environ.get("TOAD_CONTEXT_AUDIT_QUERY", "")
            if os.environ.get("TOAD_CONTEXT_AUDIT_SOURCE_ONLY") == "1":
                return "\n".join((
                    mark + "saved --wait-history-seconds 12 --wait-history-thread configured-source",
                    "key ctrl+b", "sleep 1", mark + "roster",
                    click("phase-roster-state.pickle", "right_sidebar"),
                    "sleep 7", mark + "context-open",
                    click("phase-context-open-state.pickle", "widget", "Input#context-search"),
                    "type --clearmodifiers configured-source", "key Return",
                    "sleep 2", mark + "core-matches",
                    select("phase-core-matches-state.pickle", "core"),
                    "sleep 1", mark + "core-instructions", mark + "core-expanded",
                    select("phase-core-expanded-state.pickle", "file"),
                    "sleep 3", mark + "authenticated-source", "",
                ))
            if query:
                export = os.environ["TOAD_CONTEXT_AUDIT_EXPORT"]
                return "\n".join((
                    mark + "saved --wait-history-seconds 12 --wait-history-thread configured-source",
                    "key ctrl+b", "sleep 1", mark + "roster",
                    click("phase-roster-state.pickle", "right_sidebar"),
                    "sleep 7", mark + "context-open",
                    click("phase-context-open-state.pickle", "widget", "Input#context-search"),
                    "type --clearmodifiers " + shlex.quote(query), "key Return",
                    "sleep 2", mark + "instruction-matches",
                    select("phase-instruction-matches-state.pickle", "native"),
                    "sleep 1", mark + "instruction",
                    click("phase-instruction-state.pickle", "widget", "Button#context-read-full"),
                    "sleep 1", mark + "full-read", "key Escape", "sleep 1", mark + "reader-return",
                    click("phase-reader-return-state.pickle", "widget", "Button#context-copy"),
                    "sleep 1", mark + "copied",
                    click("phase-copied-state.pickle", "widget", "Input#context-export-path"),
                    "type --clearmodifiers " + shlex.quote(export), mark + "export-path",
                    click("phase-export-path-state.pickle", "widget", "Button#context-export"),
                    "sleep 1", mark + "exported",
                    click("phase-exported-state.pickle", "widget", "Input#context-search"),
                    "key Home shift+End BackSpace", "type --clearmodifiers configured-source", "key Return",
                    "sleep 2", mark + "core-matches",
                    select("phase-core-matches-state.pickle", "core"),
                    "sleep 1", mark + "core-instructions", mark + "core-expanded",
                    select("phase-core-expanded-state.pickle", "file"),
                    "sleep 3", mark + "authenticated-source", "",
                ))
            return "\n".join((
                mark + "saved --wait-history-seconds 12 --wait-history-thread configured-source",
                "key ctrl+b", "sleep 1", mark + "roster",
                click("phase-roster-state.pickle", "right_sidebar"),
                "sleep 7", mark + "context-open",
                click("phase-context-open-state.pickle", "context_tree"),
                "key Home Down Down space", "sleep 1", mark + "segment",
                "key Down", "sleep 1", mark + "provenance",
                "key Up", "sleep 1", mark + "segment-return", "",
            ))
    return recorder, recorder_path, ColdContextJourney


async def run(options):
    sys.dont_write_bytecode = True
    core = options.core_checkout.resolve()
    sys.path.append(str(core / "tools/cutover"))
    from agent_comms.child_process import ProcessIdentity
    from agent_comms.acp import CommsAgent
    from agent_comms.comms import Comms
    from agent_comms.field_codec import FieldCodec
    from agent_comms.input_disposition import InputDispositions
    from toad.core.context_inspection import ContextInspection, RecordedSegmentNode
    from original_owner_capture import CurrentTypedCapture
    recorder, recorder_path, ColdContextJourney = load_recorder()

    started = time.monotonic()
    base = options.output.resolve()
    assert base.is_relative_to(Path.home() / ".cache/agent-scratch")
    base.mkdir(parents=True, exist_ok=False)
    runtime = options.candidate_bin.resolve(strict=True)
    assert Path(sys.prefix).resolve() == runtime.parent
    activation = json.loads((runtime.parent / "activation.json").read_text())
    package = Path(activation["native_package"])
    root = options.fixture.resolve()
    service = Comms(root / "wire")
    previous = service.registry.require("configured-source")
    selected = Path(previous.require_saved_session())
    before = selected.read_bytes()
    assert not previous.require_process().alive(), "The previous owned controller must be retired"
    original = CurrentTypedCapture(options.public_root, options.original_python).read(
        options.original_thread)
    source = original.require_current()
    public_file = Path(source.require_saved_session())
    public_before = hashlib.sha256(public_file.read_bytes()).hexdigest()
    assert source.model == previous.model and source.thinking_level == previous.thinking_level
    inputs_before = InputDispositions(service.root / InputDispositions.filename).read()
    inspection = ContextInspection.read(service, previous.name)
    manifests_before = inspection.manifests
    tags_before = previous.tags
    receipt = {"state": "PREPARING_COLD_CONFIGURED_OWNER", "fixture": str(root),
        "selected_file": str(selected), "selected_bytes": len(before),
        "selected_sha256_before": hashlib.sha256(before).hexdigest(),
        "public_file": str(public_file), "public_sha256_before": public_before,
        "model": source.model, "thinking": source.thinking_level.declared_name,
        "providers": 0, "native_inputs": 0, "priming_calls": 0,
        "python": sys.executable, "activation": str(runtime.parent / "activation.json")}
    owner = None
    try:
        environment = dict(original.retained.environment)
        with service.bus.log.locked():
            metadata = service.bus.log.read_metadata_unlocked()
        assert metadata.private, "Borrow only the already-owned private protocol root"
        root_id = metadata.root_id
        environment.update(AGENT_COMMS_ROOT=str(service.root),
            AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
            AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
            PI_COMPACTION_TEST_PACKAGE=str(package),
            AGENT_COMMS_AGENT_BIN=str(runtime / "pi-comms-native"),
            AGENT_COMMS_RUNTIME_ROOT=str(runtime),
            PATH=str(runtime) + os.pathsep + environment.get("PATH", os.defpath),
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(base / "state"),
            XDG_DATA_HOME=str(base / "data"), TOAD_TEST_ATTEMPT="Einstein-cold595-physical01")
        if options.recorded_audit:
            manifest, = (m for m in manifests_before if m.request_id == options.request_id)
            recorded = next(n for n in inspection.recorded() if n.manifest == manifest)
            system, = (n for n in recorded.children() if n.segment.kind == "system_layer")
            transcript, = (n for n in recorded.children() if n.segment.kind == "transcript")
            coordination, = (leaf for member in transcript.children() if isinstance(member, RecordedSegmentNode)
                             for leaf in member.children() if isinstance(leaf, RecordedSegmentNode)
                             and leaf.segment.kind == "coordination")
            assert 'review417' not in tags_before and 'review417-renamed' not in tags_before
            environment.update(TOAD_RECORDED_CONTEXT_AUDIT="1",
                TOAD_RECORDED_REQUEST_NODE=recorded.key, TOAD_RECORDED_SYSTEM_NODE=system.key,
                TOAD_RECORDED_TRANSCRIPT_NODE=transcript.key,
                TOAD_RECORDED_COORDINATION_NODE=coordination.key,
                TOAD_CONTEXT_AUDIT_TAGS=','.join(sorted((*tags_before, 'review417'))),
                TOAD_CONTEXT_AUDIT_EXPORT=str(base / "selected-recorded-context.txt"))
            receipt.update(sealed_request=manifest.request_id, recorded_system=system.key,
                           recorded_coordination=coordination.key)
        if options.instruction_query:
            environment.update(TOAD_CONTEXT_AUDIT_QUERY=options.instruction_query,
                               TOAD_CONTEXT_AUDIT_EXPORT=str(base / "selected-public-context.txt"))
        if options.source_only:
            environment["TOAD_CONTEXT_AUDIT_SOURCE_ONLY"] = "1"
        for name in ("PYTHONPATH", "AGENT_COMMS_THREAD", "AGENT_COMMS_STARTUP_INPUT_KEY",
                     "PI_PROMPT", "PI_PARENT_ID", "PI_TASK", "PI_AGENT_ID", "NO_COLOR"):
            environment.pop(name, None)
        os.environ.clear()
        os.environ.update(environment)
        # Restore the declared stopped source through its original producer.
        # This publishes participant membership before any live attachment;
        # it is not a reader-side grant or a fabricated delivery receipt.
        service.threads.restore_stopped(service.registry.snapshot(), (previous.name,))
        owner = CommsAgent(service, private_nk_native_package=package,
            private_nk_wire_root_id=root_id, agent_bin=str(runtime / "pi-comms-native"),
            agent_args=list(original.retained.arguments or ()), auto_wake=False,
            runtime_enabled=True)
        service.owners.pin_private_nk_launch(service.root, root_id, package)
        declared = service.owners.acquire_thread(previous.name, owner_pid=os.getpid())
        assert declared.created_at == previous.created_at
        await owner._runtime.start()
        await owner.sessions.bind_owned(declared, declared.name)
        assert declared.name not in owner.turns.persistent_backends
        assert InputDispositions(service.root / InputDispositions.filename).read() == inputs_before
        receipt["controller"] = FieldCodec.encode(declared.require_process())
        receipt["state"] = "COLD_OWNER_STARTED_NO_NATIVE_ACQUISITION"
        (base / "terminal-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        command = [str(runtime / "toad"), "acp",
            shlex.join((str(runtime / "python"), "-m", "agent_comms.acp")),
            declared.worktree, "--title", "Cold configured saved context", "--session", declared.name]
        if options.staging_receipt:
            probe_owner = recorder.ProcessOwner()
            try:
                probe = recorder.RuntimeSelection.from_environment(command, environment).publish_verified_stage(
                    options.staging_receipt, probe_owner, environment, command)
                (base / "installed-preflight.json").write_text(json.dumps(probe, indent=2) + "\n")
            finally:
                probe_owner.cleanup()
        sys.argv = [str(recorder_path), "--output", str(base / "capture"),
            "--owner", "Einstein-cold595-physical01", "--private-root", str(service.root),
            "--journey", ColdContextJourney.declared_name, "--capture-state",
            "--review-timing", "deferred", "--fps", "20", "--width", "1500",
            "--height", "1100", "--fit-window", "--startup-wait", "10",
            "--max-duration", "240" if options.recorded_audit else "110" if options.instruction_query else "65",
            "--tail-seconds", "2", "--", *command]
        (base / "caller.json").write_text(json.dumps(sys.argv, indent=2) + "\n")
        with (base / "recorder.log").open("w") as log:
            recording = await asyncio.create_subprocess_exec(sys.executable,
                str(Path(__file__).resolve()), "--record-only", *sys.argv[1:],
                stdout=log, stderr=asyncio.subprocess.STDOUT)
            assert await recording.wait() == 0, "Inspect original recorder log/receipt"
        persistent = owner.turns.persistent_backends[declared.name]
        child = persistent.custody.idle().child
        receipt["native_process"] = FieldCodec.encode(child.proc.identity)
        def phase(label):
            return pickle.loads((base / f"capture/phase-{label}-state.pickle").read_bytes())
        def context_phase(label):
            snapshot = phase(label)
            return next(view for view in snapshot["views"]
                        if view["mode"] == snapshot["metadata"]["current_mode"])["context"]
        if options.recorded_audit:
            context = context_phase("recorded-system")
            text = context["detail"]
            assert context["selected"] == system.key and "One fact" in text
            assert "Selected context detail unavailable" not in text
            assert system.key in {n["key"] for n in context_phase("recorded-search")["nodes"]}
            assert context_phase("recorded-full")["maximized"]
            assert context_phase("recorded-full")["detail"] == text
            assert context_phase("recorded-export")["clipboard"] == text
            assert (base / "selected-recorded-context.txt").read_text() == text
            child_context = context_phase("recorded-coordination")
            assert child_context["selected"] == coordination.key
            assert "Coordination context:" in child_context["detail"]
            assert "Selected context detail unavailable" not in child_context["detail"]
            saved_view = next(v for v in phase("recorded-system")["views"]
                              if v["mode"] == phase("recorded-system")["metadata"]["current_mode"])
            assert saved_view["agent_configuration"]["context_measurement"]["used"] > 0
            assert saved_view["agent_configuration"]["context_measurement"]["size"] > 0
            native_info = service.agents.agent_info_of(previous.name)
            measurement = saved_view["agent_configuration"]["context_measurement"]
            assert (measurement['used'], measurement['size']) == (native_info.context_used, native_info.context_size)
            receipt['canonical_native_usage_publication'] = FieldCodec.encode(native_info)
            assert service.registry.require(previous.name).tags == tags_before
            assert '#review417' not in service.channels.channels()
            assert '#review417-renamed' not in service.channels.channels()
            assert not any(n["id"] == "command-apply" for n in phase("deleted")["metadata"]["navigation_targets"]["widgets"])
            receipt.update(recorded_search_read_copy_export_equal=True,
                recorded_coordination_text=child_context["detail"],
                original_footer_measurement=saved_view["agent_configuration"]["context_measurement"],
                physical_menu_tag_rename_delete_and_slash=True)
            returned = context
        elif options.source_only:
            context = context_phase("core-instructions")
            assert context["native_present"] and "configured-source" in context["detail"]
            reference = context_phase("authenticated-source")
            assert reference["selected"].startswith("core/") and "/source/" in reference["selected"]
            assert "Selected context detail unavailable" not in reference["detail"]
            assert "Preparing selected" not in reference["detail"]
            assert len(reference["detail"]) > 100
            receipt.update(core_instructions=context["detail"],authenticated_source=reference,
                           prior_instruction_scope="physical03 original native full reader/copy/export retained; not repeated")
            returned = context
        elif options.instruction_query:
            context = context_phase("instruction")
            text = context["detail"]
            assert options.instruction_query.casefold() in text.casefold()
            assert context["native_present"] and len(text) > 100
            assert context_phase("full-read")["maximized"]
            assert context_phase("full-read")["detail"] == text
            assert not context_phase("reader-return")["maximized"]
            assert context_phase("copied")["clipboard"] == text
            assert (base / "selected-public-context.txt").read_text() == text
            core_text = context_phase("core-instructions")["detail"]
            assert "configured-source" in core_text
            reference = context_phase("authenticated-source")
            assert "Selected context detail unavailable" not in reference["detail"]
            assert "Preparing selected" not in reference["detail"]
            assert len(reference["detail"]) > 100
            assert reference["selected"].startswith("core/") and "/source/" in reference["selected"]
            receipt.update(instruction_query=options.instruction_query,
                full_read_copy_export_equal=True, public_characters=len(text),
                authenticated_source=reference, core_instructions=core_text)
            returned = context
        else:
            context = context_phase("provenance")
            assert context["native_present"] and "Archived context: not supplied" not in context["detail"]
            returned = context_phase("segment-return")
            assert len(returned["detail"]) > 100
        receipt["state"] = "SCOPED_COLD_TREE_TERMINAL_PASS_PENDING_PIXEL_REVIEW"
        receipt["context"] = context
        receipt["segment_text_characters"] = len(returned["detail"])
        from agent_comms.coordinator import Coordination
        from agent_comms.bus_publication import stable_thread_lookup
        with Coordination(str(service.root / "coordination.sqlite3")) as coordination:
            participant = coordination.participants.get(stable_thread_lookup(declared.created_at))
        assert participant.committed and participant.owner_thread == declared.name
        receipt["participant"] = FieldCodec.encode(participant)
        receipt["selected_sha256_after"] = hashlib.sha256(selected.read_bytes()).hexdigest()
        assert selected.read_bytes() == before
        assert hashlib.sha256(public_file.read_bytes()).hexdigest() == public_before
        original.require_current()
        assert InputDispositions(service.root / InputDispositions.filename).read() == inputs_before
        assert ContextInspection.read(service, previous.name).manifests == manifests_before
        receipt["original_manifest_and_input_unchanged"] = True
        receipt["original_source_unchanged"] = True
    except BaseException as error:
        receipt.update(state="FAILED_NO_REPLAY", error=repr(error))
        raise
    finally:
        if owner is not None:
            # Capture the original retained resource even if recorder/control
            # failure occurred before the success assertions.
            for backend in owner.turns.persistent_backends.values():
                if backend.custody.retained:
                    child = backend.custody.idle().child
                    receipt["native_process"] = FieldCodec.encode(child.proc.identity)
            await owner.shutdown()
        if "child" in locals():
            receipt["native_child_retired"] = child.proc.retired and not child.proc.alive()
        receipt["selected_sha256_after"] = hashlib.sha256(selected.read_bytes()).hexdigest()
        receipt["selected_source_unchanged"] = selected.read_bytes() == before
        receipt["public_sha256_after"] = hashlib.sha256(public_file.read_bytes()).hexdigest()
        receipt["public_source_unchanged"] = receipt["public_sha256_after"] == public_before
        receipt["original_inputs_unchanged"] = InputDispositions(
            service.root / InputDispositions.filename).read() == inputs_before
        receipt["native_input_rows_after"] = len(InputDispositions(
            service.root / InputDispositions.filename).read().rows)
        receipt["elapsed_seconds"] = time.monotonic() - started
        (base / "terminal-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--reveal-context"]:
        import subprocess
        output = Path(os.environ["TOAD_VIDEO_OUTPUT"])
        state, key = sys.argv[2:]
        snapshot = pickle.loads((output/state).read_bytes())
        focused = snapshot['metadata']['screen']['focused']
        assert (focused['class'], focused['id']) == ('Tree', 'context-tree'), 'Physical reveal requires the actually focused context Tree'
        context = next(v for v in snapshot['views'] if v['mode']==snapshot['metadata']['current_mode'])['context']
        model, = (node for node in context['nodes'] if node['key']==key)
        assert model['line'] >= 0, 'Original member must be expanded in the native Tree first'
        assert os.environ['DISPLAY'] != ':0'
        subprocess.run(['xdotool','key','Home'],check=True)
        if model['line']:
            subprocess.run(['xdotool','key','--repeat',str(model['line']),'--repeat-delay','5','Down'],check=True)
        raise SystemExit(0)
    if sys.argv[1:2] == ["--select-context"]:
        helper = Path(__file__).resolve().parents[1] / "tools/performance/click_history.py"
        spec = importlib.util.spec_from_file_location("context_native_click", helper)
        click = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = click
        spec.loader.exec_module(click)
        state, kind = sys.argv[2:]
        snapshot = click.read_snapshot(Path(state))
        context = click.NativeFocusTarget.selected_view(snapshot)["context"]
        if kind.startswith("exact:"):
            nodes = (node for node in context["nodes"] if node["key"] == kind.removeprefix("exact:"))
        elif kind == "file":
            nodes = (node for node in context["nodes"]
                     if node["key"].startswith(context["selected"] + "/source/")
                     and node["label"].startswith("Source · File "))
        else:
            nodes = (node for node in context["nodes"] if node["key"].startswith(kind + "/"))
        selected = next(node for node in nodes if node["target"] is not None)
        sys.argv = [str(helper), "--state", state, "--target", "context_tree", "--name", selected["key"]]
        click.main()
        raise SystemExit(0)
    if sys.argv[1:2] == ["--record-only"]:
        sys.argv.pop(1)
        recorder, _, _ = load_recorder()
        recorder.main()
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-bin", type=Path, required=True)
    parser.add_argument("--core-checkout", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--original-python", type=Path, required=True)
    parser.add_argument("--original-thread", default="openhcs-audit-merged-runtime")
    parser.add_argument("--recorded-audit", action="store_true")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--staging-receipt", type=Path)
    parser.add_argument("--instruction-query", default="", help="Search the original public instructions in the same cold journey")
    parser.add_argument("--source-only", action="store_true", help="Finish only Core instruction search and authenticated reading; retain earlier native reader proof")
    asyncio.run(run(parser.parse_args()))
