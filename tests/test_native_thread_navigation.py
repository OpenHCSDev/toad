"""How a native thread opens depends on whether this client's connection starts agents."""

from __future__ import annotations

from agent_comms.projects.checkouts import Checkout

from toad.client.agent_processes import NoAgentProcesses, SpawnsAgentProcesses
from toad.client.input_decision import InputAccepted
from toad.client.session_sources import MailboxSources
from toad.navigation_preparation import ExternalThreadNavigation, ThreadConversationPreparation


class HeldSession:
    """Stands for the navigation that holds the thread's agent session."""


def preparation(agents, monkeypatch, tmp_path) -> ThreadConversationPreparation:
    monkeypatch.setattr(ThreadConversationPreparation, "session", lambda self: HeldSession())
    return ThreadConversationPreparation("/bus", object(), Checkout(tmp_path), object(), agents)


def test_a_client_that_starts_agents_holds_the_native_threads_session(monkeypatch, tmp_path):
    opened = preparation(SpawnsAgentProcesses(), monkeypatch, tmp_path).native()

    assert isinstance(opened, HeldSession)


def test_a_client_on_a_ui_profile_opens_a_native_thread_through_its_inbox(monkeypatch, tmp_path):
    opened = preparation(NoAgentProcesses(), monkeypatch, tmp_path).native()

    assert type(opened) is ExternalThreadNavigation


def test_a_mailbox_takes_input_with_no_agent_on_its_tab():
    assert isinstance(MailboxSources().input_decision(object()), InputAccepted)
