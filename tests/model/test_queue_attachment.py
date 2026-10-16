"""A queue attachment captures human input only from the scope it is currently bound to."""

import os

import pytest
from agent_comms.acp_extension import (
    AvailableQueueProjection, PendingQueueProjection, QueueChangedUpdate, QueueScope,
)
from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import Comms
from agent_comms.input_origin import HumanInputOrigin
from agent_comms.threads import Thread

from toad.acp.queue_attachment import QueueAttachment


def declared_scope(tmp_path):
    comms = Comms(tmp_path / "wire")
    comms.messaging.initialize_private_initial_protocol()
    comms.registry.declare(Thread("source", frozenset(), str(tmp_path),
                                  process_identity=ProcessIdentity.capture(os.getpid())))
    return comms, QueueScope("source", comms.registry.snapshot().admission_identity("source"), os.getpid())


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
    assert attachment.capture_human_input(comms, scope) == HumanInputOrigin.capture(comms, scope.admission)


def test_capture_after_a_replacement_begins_is_refused(tmp_path):
    comms, scope = declared_scope(tmp_path)
    attachment = QueueAttachment()
    token = attachment.begin("source")
    attachment.bind(QueueChangedUpdate(scope, 0, AvailableQueueProjection()), "source", token)
    attachment.begin("source")  # keeps the old observed scope behind a pending projection
    with pytest.raises(ValueError, match="Checking input queue"):
        attachment.capture_human_input(comms, scope)
