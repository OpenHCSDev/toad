"""Session labels own whether thread presentation and identity may replace them."""

import pytest

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
    details = SessionDetails(index=1, mode_name="session-1", name=name)
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


def test_session_tracker_publishes_only_changed_labels():
    tracker = SessionTracker()
    details = tracker.new_session(title="old")
    changes = []
    with tracker.events.subscribe(lambda event, _subscription: changes.append(event)):
        tracker.bind_identity(details.mode_name, "old", "old")
        assert changes == []
        tracker.bind_identity(details.mode_name, "old", "new")
        assert details.name.display == "new"
        assert len(changes) == 1
        tracker.name_session(details.mode_name, "Chosen")
        assert len(changes) == 2
        tracker.bind_identity(details.mode_name, "new", "renamed")
        assert details.name.display == "Chosen"
        assert len(changes) == 2
