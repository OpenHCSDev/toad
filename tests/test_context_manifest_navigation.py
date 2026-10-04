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
    from textual.widgets import Button, Input, Static, TextArea
    from toad.agent_schema import AgentDefinition
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
        PI_CODING_AGENT_DIR=str(tmp_path / "pi"),
        TOAD_TEST_ATTEMPT="authored-w6-" + tmp_path.name,
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

    async def mounted():
        controller = CommsAgent(service, agent_bin=str(runtime / "pi-comms-native"),
            agent_args=["--offline", "--no-extensions", "--no-skills", "--no-context-files"],
            auto_wake=False, runtime_enabled=True,
            private_nk_native_package=package, private_nk_wire_root_id=root_id)
        try:
            assert isinstance(controller.annotations.policy, DisabledAnnotationPolicy)
            assert not controller.annotations.tasks
            service.owners.pin_private_nk_launch(service.root, root_id, package)
            service.threads.restore_stopped(service.registry.snapshot(), (receipt.thread,))
            owner = service.owners.acquire_thread(receipt.thread, owner_pid=os.getpid())
            assert owner.incarnation == original_owner.incarnation
            await controller.sessions.bind_owned(owner, owner.name)
            definition = AgentDefinition.decode({"name": "Authored W6 source",
                "identity": "agent-comms.openhcs.dev", "short_name": "comms", "protocol": "acp",
                "run_command": {"*": shlex.join((sys.executable, "-m", "agent_comms.acp"))}})
            app = ToadApp(agent_data=definition, project_dir=str(project), agent_session_id=owner.name)
            async with app.run_test(size=(130, 44)) as pilot:
                await app.selected_session.wait_content_ready()
                panel, = (bar for bar in app.selected_session.query(SideBar) if bar.right)
                assert await pilot.click(panel.query_one(SideBarToggle))
                await panel.wait_content_ready()
                explorer = app.selected_session.query_one(ContextExplorer)
                explorer.query_ancestor(SideBarCollapsible).collapsed = False
                explorer.action_refresh()
                tree = explorer.query_one(ContextTree)
                reference, = ContextInspection.read(service, owner.name).imported()
                async with asyncio.timeout(20):
                    while reference.key not in tree.context_nodes:
                        await pilot.pause(.025)
                node = tree.context_nodes[reference.key]
                node.parent.expand()
                tree.scroll_to_node(node, animate=False)
                tree.focus()
                tree.move_cursor(node)
                await pilot.pause()
                assert tree.cursor_node is node and app.focused is tree
                await pilot.press("enter")
                async with asyncio.timeout(10):
                    while instructions not in explorer.query_one(TextArea).text:
                        await pilot.pause(.025)
                inspection = ContextInspection.read(service, owner.name)
                assert inspection.recorded() == ()
                matches = await inspection.find(inspection.imported(), "historical λ")
                assert tuple(match.source for match in matches) == receipt.historical_instructions
                query = explorer.query_one("#context-search", Input)
                query.value = "historical λ"
                query.focus()
                await pilot.pause()
                assert app.focused is query
                await pilot.press("enter")
                async with asyncio.timeout(10):
                    while "1 matching sources" not in explorer.query_one(".context-status", Static).render().plain:
                        await pilot.pause(.025)
                selected = tree.context_nodes[reference.key]
                tree.focus()
                tree.move_cursor(selected)
                await pilot.pause()
                assert tree.cursor_node is selected and app.focused is tree
                exported = tmp_path / "historical-source.txt"
                explorer.query_one("#context-export-path", Input).value = str(exported)
                export_button = explorer.query_one("#context-export", Button)
                export_button.scroll_visible(animate=False, immediate=True)
                await pilot.pause()
                assert await pilot.click(export_button)
                async with asyncio.timeout(10):
                    while not exported.exists():
                        await pilot.pause(.025)
                assert instructions in exported.read_text()
                assert "not current instructions" in selected.data.label
                assert app._exception is None
            assert app._exception is None
            assert not controller.annotations.tasks
        finally:
            await controller.shutdown()
        assert source.read_bytes() == original
        assert InputDispositions(service.root / InputDispositions.filename).read() == inputs
        assert service.registry.require(receipt.thread).incarnation == original_owner.incarnation

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
