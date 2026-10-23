"""Context inspection observes the saved session and its owner proof on a real wire."""

from dataclasses import replace

from agent_comms.session_revision import SessionRevision
from agent_comms.threads import Thread

from toad.core.context_inspection import ContextInspection, HoldingInspection


def declared_reader(workspace):
    from agent_comms.fresh_private_session import create_fresh_private_session
    from agent_comms.native_session_files import NativeSessionFiles
    from agent_comms.session_file import RegistrySessionLocation

    identity = create_fresh_private_session(workspace.comms.root, worktree=workspace.project)
    registry = workspace.comms.registry
    registry.declare(Thread(
        "context-reader", frozenset(), str(workspace.project), session_file=RegistrySessionLocation.from_path(identity.session_file, workspace.comms.root)))
    thread = registry.require("context-reader")
    files = NativeSessionFiles.for_identity(
        identity, root=workspace.comms.root, owner=thread.incarnation.require_recorded())
    return thread, files


def with_thread(inspection, **changes):
    return replace(inspection, entry=replace(inspection.entry, thread=replace(inspection.entry.thread, **changes)))


def test_context_reader_observes_the_session_and_its_owner_proof(workspace):
    thread, files = declared_reader(workspace)

    before = ContextInspection.read(workspace.comms, thread.name)
    assert before.source == SessionRevision.observe(files)
    files.input_proof.parent.mkdir(parents=True, exist_ok=True)
    files.input_proof.touch()
    after = ContextInspection.read(workspace.comms, thread.name)
    assert after.source == SessionRevision.observe(files)
    assert after.source != before.source


def test_held_native_context_is_read_again_only_when_its_launch_or_session_changes(workspace):
    thread, files = declared_reader(workspace)
    read = ContextInspection.read(workspace.comms, thread.name)
    held = HoldingInspection(read, revision=1)

    assert not held.needs_native(with_thread(read, title="A new title"), False)
    assert held.needs_native(with_thread(read, model="model-b"), False)
    assert held.needs_native(with_thread(read, created_at=thread.created_at + 1.0), False)
    files.input_proof.parent.mkdir(parents=True, exist_ok=True)
    files.input_proof.touch()
    assert held.needs_native(ContextInspection.read(workspace.comms, thread.name), False)
