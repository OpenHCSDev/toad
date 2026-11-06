"""A title guessed from the first prompt stands in until the thread names itself."""

from toad.session_tracker import AuthoredSessionName, SessionDetails, ThreadSessionName


def details() -> SessionDetails:
    # The label family is what this fixes; a stand-in identity is never consulted.
    return SessionDetails(identity=object(), name=ThreadSessionName("New Session"))


def test_a_presented_title_replaces_an_earlier_guess():
    session = details()
    # What a first prompt produces today.
    assert session.update_thread_title("Updating Claude Code on Arch") is True
    assert session.name.display == "Updating Claude Code on Arch"

    # The thread names itself later: the guess yields.
    assert session.update_thread_title("Bus latency investigation") is True
    assert session.name.display == "Bus latency investigation"
    assert isinstance(session.name, ThreadSessionName)


def test_a_name_the_user_gave_is_never_replaced():
    session = SessionDetails(identity=object(), name=AuthoredSessionName("My label"))
    assert session.update_thread_title("Updating Claude Code on Arch") is False
    assert session.name.display == "My label"
