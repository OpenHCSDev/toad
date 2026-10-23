"""Context inspection observes the saved session and its owner proof on a real wire."""

from agent_comms.session_revision import SessionRevision

from toad.core.context_inspection import ContextInspection


def test_context_reader_observes_the_session_and_its_owner_proof(workspace):
    from agent_comms.fresh_private_session import create_fresh_private_session
    from agent_comms.native_session_files import NativeSessionFiles
    from agent_comms.session_file import SavedSessionFile

    identity = create_fresh_private_session(workspace.comms.root, worktree=workspace.project)
    registry = workspace.comms.registry
    registry.declare(registry.new_thread(
        "context-reader", frozenset(), str(workspace.project), session_file=SavedSessionFile(identity.session_file)))
    thread = registry.require("context-reader")
    files = NativeSessionFiles.for_identity(
        identity, root=workspace.comms.root, owner=thread.incarnation.require_recorded())

    before = ContextInspection.read(workspace.comms, thread.name)
    assert before.source == SessionRevision.observe(files)
    files.input_proof.parent.mkdir(parents=True, exist_ok=True)
    files.input_proof.touch()
    after = ContextInspection.read(workspace.comms, thread.name)
    assert after.source == SessionRevision.observe(files)
    assert after.source != before.source
