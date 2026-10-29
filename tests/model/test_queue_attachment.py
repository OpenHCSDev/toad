"""A queue attachment captures human input only from the scope it is currently bound to."""

from agent_comms.repo import Checkout
import os

import pytest
from agent_comms.acp_extension import (
    AvailableQueueProjection, PendingQueueProjection, QueueChangedUpdate, LiveQueueScope,
)
from agent_comms.child_process import ProcessIdentity
from agent_comms.input_origin import HumanInputOrigin
from agent_comms.threads import Thread

from support.roots import installed_wire

from toad.acp.queue_attachment import QueueAttachment


def declared_scope(tmp_path):
    comms = installed_wire(tmp_path / "wire")
    owner = ProcessIdentity.capture(os.getpid())
    comms.registry.declare(Thread("source", frozenset(), Checkout(tmp_path),
                                  process_identity=owner))
    return comms, LiveQueueScope(
        session_id="source", claimed_identity=comms.registry.snapshot().claimed_identity("source"), owner=owner,
    )


def test_capture_before_binding_is_refused(tmp_path):
    comms, scope = declared_scope(tmp_path)
    with pytest.raises(ValueError, match="queue"):
        QueueAttachment().capture_human_input(comms, None)


def test_prebinding_receipt_keeps_first_observation_pending(tmp_path):
    _comms, scope = declared_scope(tmp_path)
    attachment = QueueAttachment()
    attachment.begin("source")
    attachment.callback(QueueChangedUpdate(scope, 1, AvailableQueueProjection()), "source")
    assert isinstance(attachment.projection, PendingQueueProjection)


def test_capture_after_binding_names_the_bound_scope(tmp_path):
    comms, scope = declared_scope(tmp_path)
    attachment = QueueAttachment()
    token = attachment.begin("source")
    attachment.bind(QueueChangedUpdate(scope, 0, AvailableQueueProjection()), "source", token)
    assert attachment.capture_human_input(comms, scope) == HumanInputOrigin.capture(comms, scope.claimed_identity)


def test_capture_after_a_replacement_begins_is_refused(tmp_path):
    comms, scope = declared_scope(tmp_path)
    attachment = QueueAttachment()
    token = attachment.begin("source")
    attachment.bind(QueueChangedUpdate(scope, 0, AvailableQueueProjection()), "source", token)
    attachment.begin("source")  # keeps the old observed scope behind a pending projection
    with pytest.raises(ValueError, match="Checking input queue"):
        attachment.capture_human_input(comms, scope)


def test_input_start_members_dispatch_before_queue_revision_checks(tmp_path):
    from agent_comms.acp_extension import (
        IdentifiedInputStarted,
        UnidentifiedInputStarted,
    )
    from agent_comms.nominal.field_codec import InputId

    _, scope = declared_scope(tmp_path)
    attachment = QueueAttachment()
    token = attachment.begin("source")
    native_id, input_id = InputId.mint(), InputId.mint()
    unidentified = UnidentifiedInputStarted("routed", scope, 1, native_id)
    assert attachment.started(unidentified, "source") == ()
    identified = IdentifiedInputStarted("queued", scope, 2, native_id, input_id)
    assert attachment.started(identified, "source") == ()
    _, starts = attachment.bind(
        QueueChangedUpdate(scope, 1, AvailableQueueProjection()), "source", token,
    )
    assert starts == (identified,)
    assert attachment.started(identified, "source") == ()
    newer = IdentifiedInputStarted("queued", scope, 3, native_id, input_id)
    assert attachment.started(newer, "source") == (newer,)
