"""Current contributor and recorded-child navigation retain decoded members."""

import hashlib
import json
import asyncio
from functools import partial

from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.importing import ImportFormat
from agent_comms.thread_identity import TurnId, TurnIdentity
from agent_comms.threads import Thread
from agent_comms.turn_context import (
    ContextManifest,
    ContextSegment,
    OwnerProvenance,
    RecordedContextTurn,
    SystemLayerSegment,
    UserInputSegment,
)
from toad.core.context_inspection import ContextInspection, ManifestNode, NativeSegmentNode


async def select_context_source(pilot, tree, key):
    """Borrow the mounted Tree's current source after layout acquisitions."""
    await pilot.wait_for_scheduled_animations()
    tree.scroll_visible(animate=False, immediate=True)
    node = tree.reveal(key)
    assert node is not None
    tree.scroll_to_node(node, animate=False)
    await pilot.wait_for_scheduled_animations()
    # A context publication can reconcile or retire nodes during either await.
    # The original key addresses the source; the mounted Tree owns its node.
    node = tree.context_nodes[key]
    assert tree.owns_node(node)
    label = tree._get_label_region(node.line)
    assert label is not None
    geometry = pilot.app.screen.find_widget(tree)
    target = label.translate(
        tree.content_region.offset - tree.scroll_offset
    ).intersection(geometry.clip).intersection(tree.scrollable_content_region)
    assert target, "Original source label is outside the sidebar viewport"
    point = target.offset
    assert pilot.app.screen.get_widget_at(point.x, point.y)[0] is tree
    assert await pilot.click(tree, offset=tuple(point - tree.region.offset))
    # MouseDown owns focus, Click owns selection. Neither an automatic root
    # highlight nor a click somewhere in the Tree admits the requested source.
    assert tree.cursor_node is node and pilot.app.focused is tree
    assert tree.owns_node(node) and tree.intent.selected is node.data
    return node


def test_imported_instruction_reference_read_search_export_remains_historical(tmp_path):
    source = tmp_path / "authored-codex.jsonl"
    records = [
        {"type": "session_meta", "payload": {"id": "authored", "cwd": str(tmp_path)}},
        {"type": "response_item", "payload": {
            "type": "message", "role": "developer", "content": "Authored historical λ instructions."}},
        {"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": "Authored question"}},
    ]
    source.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
    original = source.read_bytes()
    service = Comms(tmp_path / "wire")
    service.messaging.initialize_private_initial_protocol()
    receipt = service.threads.import_thread(source, ImportFormat.CODEX, name="imported")
    inspection = ContextInspection.read(service, receipt.thread)
    (node,) = inspection.imported()
    assert inspection.recorded() == ()
    assert node.source == receipt.historical_instructions[0]
    assert "not current instructions" in node.label

    async def read_original():
        text = await node.read()
        assert "Authored historical λ instructions." in text
        assert await inspection.find((node,), "historical λ") == (node,)
        exported = tmp_path / "original-export.txt"
        await node.export(exported)
        assert exported.read_text() == text
        source.write_text(source.read_text().replace("historical λ", "changed θ"))
        try:
            await node.read()
        except ValueError as error:
            assert "changed or is unavailable" in str(error)
        else:
            raise AssertionError("Changed original source must be refused")

    asyncio.run(read_original())
    assert source.read_bytes() != original  # Only this authored source was deliberately changed.


def test_authored_import_registered_app_and_local_user_correction(tmp_path, monkeypatch):
    """The installed purpose uses authored history, not a model-turn witness.

    A local controlled label exercises the original USER correction operation.
    It is not published as an SDK observation or placed in recorded requests.
    The actual App reads the separately imported historical source through its
    existing explorer resource. No prompt, fork, provider or disclosure occurs.
    """
    import os
    from importlib.resources import files
    from pathlib import Path
    import shlex
    import sys

    from agent_comms.acp import CommsAgent
    from agent_comms.cli_commands import CorrectAnnotationCliCommand
    from agent_comms.coordination_tables.annotations import SpanAnnotationsRow
    from agent_comms.coordinator import Coordination
    from agent_comms.input_disposition import InputDispositions
    from agent_comms.native_package import verify_native_package
    from agent_comms.thread_identity import ThreadRole
    from agent_comms.turn_context import UnattributedProvenance
    from agent_comms.working_memory_labels import (
        AnswerProbability, HumanLabel, JevClassifier, ModelLabel, QuestionVersion,
    )
    from agent_comms.working_memory_policy import DisabledAnnotationPolicy
    from agent_comms.working_memory_questions import CommitmentSpan, KindQuestion, OtherSpan, RuleSpan
    from textual import events
    from textual._context import active_message_pump
    from textual.widgets import Button, Input, Static, TextArea
    from textual.worker import Worker
    from toad.agent_schema import AgentDefinition
    from toad.core_event_carrier import CoreEventMessage
    from l0a_native_installed_pilot import until
    from runtime_fixture import ToadApp
    from toad.widgets.context_explorer import ContextExplorer, ContextTree
    from toad.widgets.side_bar import SideBar, SideBarCollapsible, SideBarToggle

    package = Path(os.environ["AC_NATIVE_COPIED_PACKAGE"])
    verify_native_package(package)
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "authored-history.jsonl"
    instructions = "Authored historical λ rule: keep the original source."
    records = (
        {"type": "session_meta", "payload": {"id": "authored-w6", "cwd": str(project)}},
        {"type": "response_item", "payload": {
            "type": "message", "role": "developer", "content": instructions}},
        {"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": "Authored saved question"}},
        {"type": "response_item", "payload": {
            "type": "message", "role": "assistant", "content": "Authored saved answer"}},
    )
    source.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
    original = source.read_bytes()
    service = Comms(tmp_path / "wire")
    root_id = service.messaging.initialize_private_initial_protocol()
    receipt = service.threads.import_thread(source, ImportFormat.CODEX, name="authored-import")
    original_owner = service.registry.require(receipt.thread)
    inputs = InputDispositions(service.root / InputDispositions.filename).read()
    runtime = Path(sys.executable).parent
    environment = dict(
        AGENT_COMMS_ROOT=str(service.root),
        AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
        AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
        AGENT_COMMS_AGENT_BIN=str(runtime / "pi-comms-native"),
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        XDG_STATE_HOME=str(tmp_path / "state"),
        XDG_DATA_HOME=str(tmp_path / "data"),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        PI_CODING_AGENT_DIR=str(tmp_path / "pi"),
        TOAD_TEST_ATTEMPT=str(tmp_path),
        AGENT_COMMS_DEBUG_LOG=str(tmp_path / "owner-debug.log"),
    )
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ToadApp, "CSS_PATH", files("toad").joinpath("toad.tcss"))
    for key in ("PYTHONPATH", "AGENT_COMMS_ANNOTATION_POLICY", "PI_PROMPT", "PI_AGENT_ID",
                "PI_PARENT_ID", "PI_TASK", "AGENT_COMMS_THREAD", "AGENT_COMMS_STARTUP_INPUT_KEY"):
        monkeypatch.delenv(key, raising=False)

    # This controlled annotation addresses an authored local input, not the
    # imported instruction's role or an invented admitted native turn.
    segment = UserInputSegment(content="Keep the original authored source.",
                               provenance=(UnattributedProvenance(),))
    (span,) = segment.public_spans()
    classifier = JevClassifier.version()
    label = ModelLabel(span, QuestionVersion.current(KindQuestion), RuleSpan, classifier,
        (AnswerProbability(RuleSpan, .7), AnswerProbability(CommitmentSpan, .2),
         AnswerProbability(OtherSpan, .1)), .8, "authored-controlled-answer", classifier.pin)
    with Coordination(str(service.root / "coordination.sqlite3")) as store:
        with store.session.transaction() as db:
            SpanAnnotationsRow(label=label, created_at_ms=1).insert(db)
    correction = CorrectAnnotationCliCommand(
        label=label, answer=CommitmentSpan, worktree=str(project)).apply(service)
    assert isinstance(correction, HumanLabel)
    assert service.registry.require(correction.author.name).role is ThreadRole.USER
    assert correction.working_memory_section == "Promised"
    assert label.working_memory_section == "Unclassified"
    print("W6: original local USER correction committed", flush=True)

    async def mounted():
        controller = CommsAgent(service, agent_bin=str(runtime / "pi-comms-native"),
            agent_args=["--offline", "--no-extensions", "--no-skills", "--no-context-files"],
            auto_wake=False, runtime_enabled=True,
            private_nk_native_package=package, private_nk_wire_root_id=root_id)
        record = controller._debug_log

        def dispatched(message):
            # Borrow original native dispatch and worker publications. These
            # diagnostics carry names only and never decide readiness or
            # publish a second model, selection, or lifecycle state.
            if isinstance(message, (events.Mount, events.Ready, events.Focus,
                                    events.Blur, events.Show, events.Hide)):
                pump = active_message_pump.get()
                record(f"W6: {type(pump).__name__}.{type(message).__name__} dispatch")
            elif isinstance(message, Worker.StateChanged):
                worker = message.worker
                record(f"W6: {type(worker.node).__name__} worker "
                       f"{worker.group}/{worker.name} {message.state.name}")
            elif isinstance(message, CoreEventMessage):
                record(f"W6: original {type(message.event).__name__} dispatch")
            elif isinstance(message, (events.MouseDown, events.MouseUp, events.Click)):
                pump = active_message_pump.get()
                record(f"W6: {type(pump).__name__}.{type(message).__name__} "
                       f"at={message.screen_offset} style={message.style.meta}")
            elif isinstance(message, ContextTree.NodeHighlighted):
                record(f"W6: native Tree highlight node={message.node.id}")

        try:
            record("W6: original local USER correction committed; controller constructed")
            assert isinstance(controller.annotations.policy, DisabledAnnotationPolicy)
            assert not controller.annotations.tasks
            record("W6: acquiring original private launch and stopped-source restoration")
            service.owners.pin_private_nk_launch(service.root, root_id, package)
            service.threads.restore_stopped(service.registry.snapshot(), (receipt.thread,))
            owner = service.owners.acquire_thread(receipt.thread, owner_pid=os.getpid())
            assert owner.incarnation == original_owner.incarnation
            record("W6: original owner acquired; awaiting bind_owned")
            await controller.sessions.bind_owned(owner, owner.name)
            record("W6: canonical owner acquired and runtime bound")
            definition = AgentDefinition.decode({"name": "Authored W6 source",
                "identity": "agent-comms.openhcs.dev", "short_name": "comms", "protocol": "acp",
                "run_command": {"*": shlex.join((sys.executable, "-m", "agent_comms.acp"))}})
            app = ToadApp(agent_data=definition, project_dir=str(project), agent_session_id=owner.name)
            record("W6: entering original registered App startup and screen barrier")
            async with app.run_test(size=(130, 44), message_hook=dispatched) as pilot:
                record("W6: App entered; awaiting original content readiness")
                await app.selected_session.wait_content_ready()
                record("W6: content ready; awaiting frame-admitted ACP agent construction")
                conversation = app.selected_session.conversation
                await until(pilot, lambda: conversation.agent is not None)
                agent = conversation.agent
                record("W6: ACP agent constructed; awaiting original session attachment settlement")
                await agent.session.settled.wait()
                assert agent.ready, "Original ACP attachment settled without admitting this session"
                assert agent.session_id == owner.name
                await pilot.pause()
                fact = app.coordination_facts.get(app.selected_session)
                assert fact is not None, "Original ACP source binding was not published to the selected view"
                assert fact.thread == owner.incarnation
                assert Path(fact.wire_root).resolve() == service.root.resolve()
                record("W6: original ACP session and published source binding admitted; opening sidebar")
                panel, = (bar for bar in app.selected_session.query(SideBar) if bar.right)
                assert await pilot.click(panel.query_one(SideBarToggle))
                await panel.wait_content_ready()
                record("W6: original right sidebar hydrated")
                explorer = app.selected_session.query_one(ContextExplorer)
                explorer.query_ancestor(SideBarCollapsible).collapsed = False
                explorer.action_refresh()
                tree = explorer.query_one(ContextTree)
                record("W6: acquiring original imported reference and waiting for its tree node")
                reference, = ContextInspection.read(service, owner.name).imported()
                async with asyncio.timeout(20):
                    while reference.key not in tree.context_nodes:
                        await pilot.pause(.025)
                await select_context_source(pilot, tree, reference.key)
                record("W6: original imported source selected; dispatching native Enter")
                await pilot.press("enter")
                async with asyncio.timeout(10):
                    while instructions not in explorer.query_one(TextArea).text:
                        await pilot.pause(.025)
                record("W6: authenticated historical text displayed")
                inspection = ContextInspection.read(service, owner.name)
                assert inspection.recorded() == ()
                matches = await inspection.find(inspection.imported(), "historical λ")
                assert tuple(match.source for match in matches) == receipt.historical_instructions
                query = explorer.query_one("#context-search", Input)
                query.value = "historical λ"
                query.scroll_visible(animate=False, immediate=True)
                await pilot.wait_for_scheduled_animations()
                assert await pilot.click(query, offset=(1, 1))
                assert app.focused is query
                record("W6: dispatching original historical search")
                await pilot.press("enter")
                async with asyncio.timeout(10):
                    while "1 matching sources" not in explorer.query_one(".context-status", Static).render().plain:
                        await pilot.pause(.025)
                record("W6: historical search completed")
                await select_context_source(pilot, tree, reference.key)
                exported = tmp_path / "historical-source.txt"
                explorer.query_one("#context-export-path", Input).value = str(exported)
                export_button = explorer.query_one("#context-export", Button)
                export_button.scroll_visible(animate=False, immediate=True)
                await pilot.wait_for_scheduled_animations()
                record("W6: dispatching original selected-source export")
                assert await pilot.click(export_button)
                async with asyncio.timeout(10):
                    while not exported.exists():
                        await pilot.pause(.025)
                assert instructions in exported.read_text()
                assert "not current instructions" in selected.data.label
                assert app._exception is None
                record("W6: original historical export completed; joining original App")
            assert app._exception is None
            assert not controller.annotations.tasks
            record("W6: registered App retired")
        finally:
            record("W6: joining original controller resources")
            await controller.shutdown()
            record("W6: controller resources joined")
        assert source.read_bytes() == original
        assert InputDispositions(service.root / InputDispositions.filename).read() == inputs
        assert service.registry.require(receipt.thread).incarnation == original_owner.incarnation

    asyncio.run(mounted())


async def inspect_authentic_annotation_gui(controller, session, *, project, session_file,
                                          system_file, original_file, monkeypatch):
    """Audit one authentic recorded source through the original mounted GUI."""
    from importlib.resources import files
    from pathlib import Path
    import shlex
    import sys
    from agent_comms.coordination_tables.annotations import AnnotationRequestsRow, SpanAnnotationsRow
    from agent_comms.coordinator import Coordination
    from agent_comms.thread_identity import ThreadRole
    from agent_comms.turn_context import ContextSpan, FileProvenance
    from agent_comms.working_memory_annotations import WorkingMemoryAnnotations
    from agent_comms.working_memory_labels import AnswerProbability, HumanLabel, JevClassifier, ModelLabel, QuestionVersion
    from agent_comms.working_memory_policy import DisabledAnnotationPolicy
    from agent_comms.working_memory_questions import CommitmentSpan, KindQuestion, OtherSpan, RuleSpan
    from textual.widgets import Button, TextArea
    from native_proof_cases import read_proof_rows
    from l0a_native_installed_pilot import until
    from runtime_fixture import ToadApp
    from toad.agent_schema import AgentDefinition
    from toad.core.context_inspection import AnnotationNode
    from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
    from toad.widgets.context_explorer import ContextExplorer, ContextTree
    from toad.widgets.side_bar import SideBar, SideBarCollapsible, SideBarToggle
    service = controller._comms
    owner = service.registry.require(session)
    assert isinstance(controller.annotations.policy, DisabledAnnotationPolicy)
    assert not controller.annotations.tasks
    original_source = FileProvenance(str(system_file), hashlib.sha256(original_file).hexdigest())
    authored = original_file.decode()
    monkeypatch.setattr(ToadApp, "CSS_PATH", files("toad").joinpath("toad.tcss"))
    with WorkingMemoryAnnotations.reading(service.root / "coordination.sqlite3") as db:
        assert tuple(SpanAnnotationsRow.select(db)) == ()
    history = service.bus.log.context_manifests(session, service.registry)
    (sealed,) = (manifest for manifest in history if manifest.request_id)
    manifest = ContextManifest.for_request(history, sealed.turn, sealed.require_request_id())
    assert manifest.thread == owner.incarnation
    inspection = ContextInspection.read(service, session)
    (request,) = inspection.recorded()
    assert request.manifest == manifest
    (system,) = (source for root in request.children()
                 for source in root.original_segments()
                 if source.segment.kind is SystemLayerSegment)
    original = await system.source_text()
    # Ranges come from the sealed emitted assembly; no substring
    # search or today's file reread supplies request attribution.
    file_ranges = tuple(coordinates
        for coordinates in system.segment.source_spans
        if original_source in coordinates.provenance)
    assert "".join(coordinates.public_text(original.text)
                  for coordinates in file_ranges) == authored
    spans = tuple(ContextSpan(system.segment.sha256, sentence)
        for coordinates in file_ranges
        for sentence in coordinates.sentences(original.text))
    assert len(spans) == 2
    assert all(system.segment.contains_span(span) for span in spans)
    # Sentence coordinates exclude whitespace-only separators;
    # the original file ranges above still attest those bytes.
    assert tuple(span.coordinates.public_text(original.text) for span in spans) == (
        "Keep the authored source unchanged.",
        "Deliver the authored answer.",
    )
    classifier = JevClassifier.version()
    question = QuestionVersion.current(KindQuestion)
    labels = tuple(ModelLabel(span, question, RuleSpan, classifier,
        (AnswerProbability(RuleSpan, .7), AnswerProbability(CommitmentSpan, .2),
         AnswerProbability(OtherSpan, .1)), .8,
        f"authored-local-control-{index}", classifier.pin)
        for index, span in enumerate(spans))
    with Coordination(str(service.root / "coordination.sqlite3")) as store:
        with store.session.transaction() as db:
            for label in labels:
                SpanAnnotationsRow(label=label, created_at_ms=store.session.now()).insert(db)
    assert all(label.working_memory_section == "Unclassified" for label in labels)
    native_before_gui = session_file.read_bytes()
    definition = AgentDefinition.decode({"name": "Authored W6 annotation source",
        "identity": "agent-comms.openhcs.dev", "short_name": "comms", "protocol": "acp",
        "run_command": {"*": shlex.join((sys.executable, "-m", "agent_comms.acp"))}})
    app = ToadApp(agent_data=definition, project_dir=str(project),
                  agent_session_id=session)
    async with app.run_test(size=(130, 44)) as pilot:
        await app.selected_session.wait_content_ready()
        conversation = app.selected_session.conversation
        await until(pilot, lambda: conversation.agent is not None)
        agent = conversation.agent
        await agent.session.settled.wait()
        assert agent.ready and agent.session_id == session
        await pilot.pause()
        fact = app.coordination_facts[app.selected_session]
        assert fact.thread == owner.incarnation
        assert Path(fact.wire_root).resolve() == service.root.resolve()
        panel, = (bar for bar in app.selected_session.query(SideBar) if bar.right)
        assert await pilot.click(panel.query_one(SideBarToggle))
        await panel.wait_content_ready()
        explorer = app.selected_session.query_one(ContextExplorer)
        explorer.query_ancestor(SideBarCollapsible).collapsed = False
        explorer.action_refresh()
        tree = explorer.query_one(ContextTree)
        for label, answer in zip(labels, (RuleSpan, CommitmentSpan), strict=True):
            current = ContextInspection.read(service, session)
            (model,) = (annotation for _, groups, _ in current.working_memory()
                        for group in groups for annotation in group.children()
                        if annotation.annotation.span == label.span)
            await until(pilot, lambda: any(
                group.data.reader_path(model.key)
                for group in tree.context_nodes.values()))
            await select_context_source(pilot, tree, model.key)
            await pilot.press("enter")
            span_text = label.span.coordinates.public_text(original.text)
            await until(pilot, lambda: span_text in explorer.query_one(TextArea).text)
            assert original_source.public_description() in explorer.query_one(TextArea).text
            button = explorer.query_one("#context-correct", Button)
            button.scroll_visible(animate=False, immediate=True)
            await pilot.wait_for_scheduled_animations()
            assert await pilot.click(button)
            await until(pilot, lambda: isinstance(app.screen, ContextMenu))
            menu = app.screen
            (item,) = (item for item in menu.query(ContextMenuItem)
                       if item.action == answer.declared_name)
            assert await pilot.click(item)
            await until(pilot, lambda: app.screen is not menu)
            await until(pilot, lambda: any(
                isinstance(node.data, AnnotationNode)
                and isinstance(node.data.annotation, HumanLabel)
                and node.data.annotation.span == label.span
                and node.data.annotation.answer is answer
                for node in tree.context_nodes.values()))
            rows = await Coordination.run_worker(partial(
                WorkingMemoryAnnotations.labels,
                service.root / "coordination.sqlite3", label.span, question, classifier))
            effective = SpanAnnotationsRow.effective(rows)
            assert isinstance(effective, HumanLabel) and effective.answer is answer
            assert service.registry.require(effective.author.name).role is ThreadRole.USER
            assert effective.span == label.span
            groups = ContextInspection.read(service, session).working_memory()
            (section,) = (title for title, sources, _ in groups
                         for source in sources for annotation in source.children()
                         if annotation.annotation == effective)
            assert section == effective.working_memory_section
            (refreshed,) = (node for node in tree.context_nodes.values()
                            if isinstance(node.data, AnnotationNode)
                            and node.data.annotation == effective)
            await select_context_source(pilot, tree, refreshed.data.key)
            await pilot.press("enter")
            await until(pilot, lambda: effective.public_description()
                        in explorer.query_one(TextArea).text)
            assert span_text in explorer.query_one(TextArea).text
            print(f"W6 GUI: original USER correction visible in {section}", flush=True)
    assert service.bus.log.context_manifests(session, service.registry) == history
    assert session_file.read_bytes() == native_before_gui
    assert system_file.read_bytes() == original_file
    assert len(read_proof_rows(session_file)) == 1
    assert not controller.annotations.tasks
    with WorkingMemoryAnnotations.reading(service.root / "coordination.sqlite3") as db:
        assert tuple(AnnotationRequestsRow.select(db)) == ()
    print(json.dumps({"original_request": manifest.require_request_id(),
        "original_turn": FieldCodec.encode(manifest.turn),
        "actual_span_coordinates": [FieldCodec.encode(span) for span in spans],
        "stored_native_input_proofs": len(read_proof_rows(session_file)),
        "external_annotations": 0, "scope": "Authentic AnnotationNode GUI, not W7 calibration"}),
        flush=True)


def test_authentic_recorded_annotation_gui_correction(tmp_path, monkeypatch):
    """One separately granted localhost input authors the request being audited.

    Controlled model rows address that request's original assembly spans.
    Human corrections must traverse the mounted GUI and original ACP/RPC.
    """
    import os
    from pathlib import Path
    from acp.agent.router import build_agent_router
    from agent_comms.native_package import verify_native_package
    from agent_comms.working_memory_policy import DisabledAnnotationPolicy
    from native_backend_fixture import native_backend_fixture

    package = Path(os.environ["PI_COMPACTION_TEST_PACKAGE"])
    assert package.resolve() == Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]).resolve()
    verify_native_package(package)
    system_file = tmp_path / "authored-system.txt"
    authored = "Keep the authored source unchanged.\nDeliver the authored answer.\n"
    system_file.write_text(authored)
    original_file = system_file.read_bytes()
    for name, directory in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"),
                            ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(name, str(tmp_path / directory))
    monkeypatch.setenv("TOAD_TEST_ATTEMPT", str(tmp_path))
    monkeypatch.setenv("AGENT_COMMS_DEBUG_LOG", str(tmp_path / "owner-debug.log"))
    for key in ("PYTHONPATH", "AGENT_COMMS_ANNOTATION_POLICY", "PI_PROMPT", "PI_AGENT_ID",
                "PI_PARENT_ID", "PI_TASK", "AGENT_COMMS_THREAD", "AGENT_COMMS_STARTUP_INPUT_KEY"):
        monkeypatch.delenv(key, raising=False)

    async def mounted():
        async with native_backend_fixture(tmp_path) as native:
            # Preserve --no-context-files. Explicit system-file loading is the
            # original W1 assembly path, not an AGENTS.md discovery bypass.
            options = ("--no-tools", "--system-prompt", str(system_file))
            async with native.open_owner(runtime_enabled=True, native_options=options) as (controller, session):
                assert isinstance(controller.annotations.policy, DisabledAnnotationPolicy)
                router = build_agent_router(controller)
                print("W6 GUI: issuing one original authored localhost ACP input", flush=True)
                response = await router("session/prompt", {
                    "sessionId": session,
                    "prompt": [{"type": "text", "text": "Give the authored local answer."}],
                }, False)
                assert response.stop_reason == "end_turn"
                assert native.provider.posts == 1 and len(native.saved_inputs()) == 1
                assert not controller.annotations.tasks
                await inspect_authentic_annotation_gui(controller, session,
                    project=native.project, session_file=native.session,
                    system_file=system_file, original_file=original_file, monkeypatch=monkeypatch)
                assert native.provider.posts == 1 and len(native.saved_inputs()) == 1

    asyncio.run(mounted())


def test_authentic_recorded_annotation_gui_continuation(tmp_path, monkeypatch):
    """Reacquire authentic01's original stopped source; never issue another input."""
    import os
    from pathlib import Path
    from unittest.mock import patch

    from agent_comms.coordinator import Coordination
    from agent_comms.native_package import verify_native_package
    from agent_comms.thread_identity import ThreadIncarnation
    from delivery_owner_fixture import canonical_agent
    from native_backend_fixture import NativeBackendFixture

    accepted = Path(__file__).resolve().parents[1] / (
        "evidence/working-memory-view-20261004/authentic01/private-fixture-readback.json")
    receipt = json.loads(accepted.read_text())
    fixture = Path(receipt["fixture"])
    service = Comms(fixture / "wire")
    original_owner = service.registry.require(receipt["thread"])
    incarnation = FieldCodec.decode(ThreadIncarnation, receipt["incarnation"])
    assert original_owner.incarnation == incarnation
    session_file = Path(receipt["native_session"])
    system_file = Path(receipt["source"])
    original_file = system_file.read_bytes()
    original_native = session_file.read_bytes()
    proof_file = Path(str(session_file) + ".input-proof")
    original_proof = proof_file.read_bytes()
    assert hashlib.sha256(original_file).hexdigest() == receipt["source_sha256"]
    assert hashlib.sha256(original_native).hexdigest() == receipt["native_session_sha256"]
    assert hashlib.sha256(original_proof).hexdigest() == receipt["input_proof_sha256"]
    assert original_owner.session_file == str(session_file)
    history = service.bus.log.context_manifests(original_owner.name, service.registry)
    (sealed,) = (manifest for manifest in history if manifest.request_id == receipt["request"])
    assert sealed.thread == incarnation and FieldCodec.encode(sealed.turn) == receipt["turn"]
    ContextManifest.for_request(history, sealed.turn, receipt["request"])
    with service.bus.log.locked():
        metadata = service.bus.log.read_metadata_unlocked()
    assert metadata.private
    package = Path(os.environ["PI_COMPACTION_TEST_PACKAGE"])
    assert package.resolve() == Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]).resolve()
    verify_native_package(package)
    environment = {
        "AGENT_COMMS_ROOT": str(service.root),
        "AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID": metadata.root_id,
        "AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE": str(package),
        "AGENT_COMMS_NATIVE_CONFIG_DIR": str(fixture / "config"),
        "PI_CODING_AGENT_DIR": str(fixture / "config"),
    }
    for name, directory in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"),
                            ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(name, str(tmp_path / directory))
    monkeypatch.setenv("TOAD_TEST_ATTEMPT", str(tmp_path))
    monkeypatch.setenv("AGENT_COMMS_DEBUG_LOG", str(tmp_path / "owner-debug.log"))
    for key in ("PYTHONPATH", "AGENT_COMMS_ANNOTATION_POLICY", "PI_PROMPT", "PI_AGENT_ID",
                "PI_PARENT_ID", "PI_TASK", "AGENT_COMMS_THREAD", "AGENT_COMMS_STARTUP_INPUT_KEY"):
        monkeypatch.delenv(key, raising=False)

    async def mounted():
        with patch.dict(os.environ, environment):
            controller = canonical_agent(service, auto_wake=False, runtime_enabled=True,
                agent_bin="pi", agent_args=NativeBackendFixture.native_arguments(
                    options=("--no-tools", "--system-prompt", str(system_file))))
            controller.on_connect(None)
            try:
                def acquire():
                    service.threads.restore_stopped(service.registry.snapshot(),
                                                    (original_owner.name,))
                    return service.owners.acquire_thread(original_owner.name, owner_pid=os.getpid())

                owned = await Coordination.run_worker(acquire)
                assert owned.incarnation == incarnation and owned.session_file == str(session_file)
                await controller.sessions.bind_owned(owned, owned.name)
                print("W6 GUI: acquired preserved authentic request; ZERO new input", flush=True)
                await inspect_authentic_annotation_gui(controller, owned.name,
                    project=Path(owned.worktree), session_file=session_file,
                    system_file=system_file, original_file=original_file, monkeypatch=monkeypatch)
            finally:
                await controller.shutdown()
                assert not controller.turns.turn_tasks and not controller.inputs.backend_inboxes
                assert not controller.turns.persistent_backends
        assert service.bus.log.context_manifests(original_owner.name, service.registry) == history
        assert session_file.read_bytes() == original_native
        assert proof_file.read_bytes() == original_proof
        assert system_file.read_bytes() == original_file
        assert not tuple((service.root / "runtime").glob("*.sock"))

    asyncio.run(mounted())



def test_decoded_current_contributor_and_recorded_child_labels(tmp_path):
    service = Comms(tmp_path / "wire")
    service.messaging.initialize_private_initial_protocol()
    owner = service.registry.declare(Thread("annotation-owner", frozenset(), str(tmp_path)))
    source = OwnerProvenance(owner.incarnation, "original-fixture-annotation")
    text = "Public contributor annotation"
    contribution = UserInputSegment(provenance=(source,), content=text).manifest(7)
    original = SystemLayerSegment(
        provenance=(source,), content=text, tokens=7,
        sha256=hashlib.sha256(text.encode()).hexdigest(), utf8_bytes=len(text.encode()),
        contributors=(contribution,),
    )
    current = FieldCodec.decode(ContextSegment, FieldCodec.encode(original))
    turn = RecordedContextTurn(TurnId("annotation-only"), TurnIdentity(owner.incarnation, 1))
    manifest = ContextManifest(owner.incarnation, turn, (original.measured_manifest(),),
                               "fixture.estimate")
    service.bus.log.record_context(manifest)
    inspection = ContextInspection.read(service, owner.name)
    captured = inspection.manifests[0]
    read_reference = partial(inspection.recorded_source, captured, 0)
    current_child = NativeSegmentNode("current", current, read_reference).children()[0]
    recorded_parent = inspection.recorded()[0].children()[0]
    recorded_child = recorded_parent.children()[0]
    assert service.bus.log.total_messages() == 0
    assert isinstance(current_child, ManifestNode) and isinstance(recorded_child, ManifestNode)
    assert current_child.segment.kind is recorded_child.segment.kind is UserInputSegment
    assert current_child.label == recorded_child.label == "User Input · 7 estimated tokens"
    for node in (current_child, recorded_child):
        detail = node.detail()
        assert detail.startswith("User Input\nEstimate: 7 tokens\n")
        assert contribution.sha256 in detail and "<class" not in detail
    assert recorded_parent.segment.kind is SystemLayerSegment
    assert recorded_parent.label == "System Layer · 7 estimated tokens"
