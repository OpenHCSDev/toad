"""BusQueueSource folds visible-message delivery status into the compact info-bar hint."""

from __future__ import annotations

from types import SimpleNamespace

from agent_comms.messaging.frozen_recipient import FrozenRecipient
from agent_comms.messaging.message_notification import MessageNotification
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.messaging.notification_progress import (
    AnsweredProgress,
    AnsweredResponse,
    CompletedProgress,
    HumanReadProgress,
    IgnoredProgress,
    PassiveProgress,
    PendingProgress,
    QueuedProgress,
    SentProgress,
    ShownToModelProgress,
    UnrecordedProgress,
)
from agent_comms.nominal.field_codec import MessageId, ThreadLookup

from toad.client.bus_submission import SubmittingTexts
from toad.client.notification_status import CheckedNotifications, MessageQueueEntry
from toad.client.prompt_composer import PromptComposer
from toad.submission_queue import BusQueueSource, QueueEvidence


def _fake_evidence(*, submitting: tuple[str, ...] = (), held_entries: int = 0) -> QueueEvidence:
    entries = tuple(
        SimpleNamespace(
            reference=f"ref-{i}",
            summary=f"msg-{i}",
            status=SimpleNamespace(queued_recipients=(SimpleNamespace(lookup=f"peer-{i}", canonical_thread=f"peer-{i}"),)),
        )
        for i in range(held_entries)
    )
    target = SimpleNamespace(queue_entries=lambda: entries)
    return QueueEvidence(
        presentation=None,  # type: ignore[arg-type]
        submitting=SubmittingTexts(submitting),
        busy=False,
        read_targets=lambda: (target,),
        observing=lambda: None,  # type: ignore[arg-type]
    )


def test_bus_queue_summary_omits_visible_messages_banner_and_uses_info_bar_hint() -> None:
    source = BusQueueSource()
    evidence = _fake_evidence(held_entries=3)

    assert source.holds_input(evidence) is True
    assert source.queue_summary(evidence) == ""
    assert source.held_count(evidence) == 3
    assert source.queue_hint(evidence) == "⧗ 3 held"


def test_bus_queue_summary_still_shows_actively_submitting_messages() -> None:
    source = BusQueueSource()
    evidence = _fake_evidence(submitting=("hello world",), held_entries=2)

    assert "Submitting (1): hello world" == source.queue_summary(evidence)
    assert "visible messages" not in source.queue_summary(evidence)
    assert source.held_count(evidence) == 3


def test_prompt_composer_shows_queue_hint_whenever_summary_band_is_empty() -> None:
    class _Composer(PromptComposer):
        def __init__(self, summary: str, hint: str, preview: bool) -> None:
            self.submissions = SimpleNamespace(queue_summary=summary, queue_hint=hint)
            self.kept_delivery_preview = preview

        @property
        def settings(self):
            return SimpleNamespace(ui=SimpleNamespace(input=SimpleNamespace(delivery_preview=self.kept_delivery_preview)))

        def sync_queue(self) -> None:
            pass

        def show_failure(self, text: str) -> None:
            pass

        def append_to_draft(self, suffix: str) -> None:
            pass

    # Bus view with held recipients: summary band is empty, so info-bar hint shows even with preview=True.
    bus_composer = _Composer(summary="", hint="⧗ 2 held", preview=True)
    assert bus_composer.queue_summary == ""
    assert bus_composer.queue_hint == "⧗ 2 held"

    # Native agent view with preview=True: summary band is populated, so hint stays hidden.
    native_composer = _Composer(summary="Queued (2): a · b", hint="⧗ 2 held", preview=True)
    assert native_composer.queue_summary == "Queued (2): a · b"
    assert native_composer.queue_hint == ""

    # Native agent view with preview=False: summary band hidden, hint shows.
    native_hidden = _Composer(summary="Queued (2): a · b", hint="⧗ 2 held", preview=False)
    assert native_hidden.queue_summary == ""
    assert native_hidden.queue_hint == "⧗ 2 held"


def test_checked_notifications_only_counts_actually_queued_recipients() -> None:
    """Sent, passive, read, ignored, completed, and answered recipients are not queued."""
    sender = ThreadLookup("user")

    def _notif(name: str, state) -> MessageNotification:
        return MessageNotification(
            recipient_identity=FrozenRecipient(ThreadLookup(name), name),
            sender_lookup=sender,
            state=state,
        )

    reply = AnsweredResponse(MessageReference(99, MessageId("deadbeef0001")), received_at_ms=2000)
    notifications = (
        _notif("sent-peer", SentProgress(1000)),
        _notif("passive-peer", PassiveProgress(SentProgress(1000))),
        _notif("human-peer", HumanReadProgress()),
        _notif("unrecorded-peer", UnrecordedProgress()),
        _notif("ignored-peer", IgnoredProgress(SentProgress(1000))),
        _notif("completed-peer", CompletedProgress(SentProgress(1000))),
        _notif("answered-peer", AnsweredProgress(SentProgress(1000), reply)),
        _notif("read-peer", ShownToModelProgress(1000)),
        _notif("queued-peer", QueuedProgress(1000)),
        _notif("pending-queued-peer", PendingProgress(QueuedProgress(1000))),
        _notif("pending-sent-peer", PendingProgress(SentProgress(1000))),
    )
    status = CheckedNotifications(notifications)
    assert [r.canonical_thread for r in status.queued_recipients] == [
        "queued-peer",
        "pending-queued-peer",
    ]

    # When nothing is queued (only sent/passive/read), BusQueueSource hides held/queue UX completely.
    quiet_status = CheckedNotifications(notifications[:8])
    assert quiet_status.queued_recipients == ()
    quiet_entry = MessageQueueEntry(MessageReference(1, MessageId("deadbeef0002")), quiet_status)
    quiet_target = SimpleNamespace(queue_entries=lambda: (quiet_entry,))
    quiet_evidence = QueueEvidence(
        presentation=None,  # type: ignore[arg-type]
        submitting=SubmittingTexts(()),
        busy=False,
        read_targets=lambda: (quiet_target,),
        observing=lambda: None,  # type: ignore[arg-type]
    )
    source = BusQueueSource()
    assert source.holds_input(quiet_evidence) is False
    assert source.held_count(quiet_evidence) == 0
    assert source.queue_hint(quiet_evidence) == ""
