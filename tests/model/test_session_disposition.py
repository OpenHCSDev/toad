"""An ordinary session presentation preserves the thread's own activity."""
from toad.acp.session_disposition import SessionDisposition


def test_ordinary_session_shows_the_threads_own_state():
    state = SessionDisposition()
    assert state.present("⌛ Working", lambda status: status.notice) == "⌛ Working"
