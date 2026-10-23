"""Session labels own whether thread presentation and identity may replace them."""

import pytest

from toad.core.events import SessionChangedEvent
from toad.db import DB
from toad.tab_order import TabOrder
from toad.tab_identity.kinds import AcpTab
from toad.session_tracker import (
    AuthoredSessionName,
    SessionDetails,
    SessionTracker,
    ThreadSessionName,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        (AuthoredSessionName("Chosen"), "Chosen"),
        (AuthoredSessionName("New Session"), "New Session"),
        (ThreadSessionName("New Session"), "Presented title"),
        (ThreadSessionName("Old title"), "Presented title"),
        (ThreadSessionName("Presented title"), "Presented title"),
    ],
)
def test_session_label_owns_presented_title(name, expected):
    details = SessionDetails(identity=AcpTab(1), name=name)
    assert details.update_thread_title("Presented title") == (name.display != expected)
    assert details.name.display == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        (AuthoredSessionName("old"), "old"),
        (AuthoredSessionName("New Session"), "New Session"),
        (ThreadSessionName("New Session"), "new"),
        (ThreadSessionName("old"), "new"),
        (ThreadSessionName("Unrelated title"), "Unrelated title"),
    ],
)
def test_session_label_owns_identity_change(name, expected):
    assert name.adopt_identity("old", "new").display == expected


class SessionChanges(list[SessionChangedEvent]):
    def record(self, event: SessionChangedEvent, _subscription) -> None:
        self.append(event)


def test_session_tracker_publishes_only_changed_labels(tmp_path):
    order = TabOrder(lambda identity, index: None, home="home", db=DB(tmp_path / "toad.db"))
    tracker = SessionTracker(order)
    details = tracker.new_session(AcpTab(1), title="old")
    changes = SessionChanges()
    with tracker.events.subscribe(SessionChangedEvent, changes.record):
        tracker.bind_identity(details.identity, "old", "old")
        assert changes == []
        tracker.bind_identity(details.identity, "old", "new")
        assert details.name.display == "new"
        assert len(changes) == 1
        tracker.name_session(details.identity, "Chosen")
        assert len(changes) == 2
        tracker.bind_identity(details.identity, "new", "renamed")
        assert details.name.display == "Chosen"
        assert len(changes) == 2
