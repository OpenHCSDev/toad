"""How a native thread opens depends on whether this client's connection starts agents."""

from __future__ import annotations

from agent_comms.projects.checkouts import Checkout

from toad.client.agent_processes import NoAgentProcesses, SpawnsAgentProcesses
from toad.client.input_decision import InputAccepted
from toad.client.session_scope import BoundSources
from toad.client.session_sources import MailboxSources, SessionSources
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


class BoundView(BoundSources):
    """A view thread navigation binds, keeping its sources on itself."""

    def __init__(self) -> None:
        self.operational_sources = SessionSources()


def test_a_view_opened_through_the_inbox_takes_mailbox_sources():
    view = BoundView()

    view.apply_external_mailbox_sources()

    assert type(view.operational_sources) is MailboxSources


def test_a_view_gives_its_sources_the_native_threads_load_plan():
    view, plan = BoundView(), object()

    view.apply_native_load_plan(plan)

    assert view.operational_sources.load_plan is plan


def test_both_frontends_views_answer_the_bind_hooks_from_the_shared_parent():
    from toad.qt.mailbox_view import QtMailboxView
    from toad.screens.main import MainScreen

    for view in (MainScreen, QtMailboxView):
        for hook in ("apply_external_mailbox_sources", "apply_native_load_plan"):
            assert getattr(view, hook) is getattr(BoundSources, hook), (view, hook)
