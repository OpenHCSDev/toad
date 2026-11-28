"""Tests for unified inbox model picker, provider catalog, and cross-provider fork routing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from agent_comms.comms import Comms
from agent_comms.installer.active_route import CommsRoute
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.registry.thread_model import (
    CliInboxSelection,
    DeclaredModel,
    ModelSelection,
)
from agent_comms.registry.thread_status import StoppedThreadStatus
from agent_comms.registry.thread_text import ForkedParent
from agent_comms.registry.threads import NativeThread
from agent_comms.transport.served_tools.served import ServedRequest
from agent_comms.transport.tool_caller import HumanCaller
from PySide6.QtWidgets import QApplication, QWidget

from toad.client.model_selection import (
    ModelChoice,
    ProviderChoiceSelection,
    merge_provider_model_choices,
)
from toad.qt.acp_tab import QtAcpSessionView
from toad.qt.mailbox_view import QtMailboxView
from toad.qt.model_selection import QtModelChoiceDialog, QtProviderModelSelection
from toad.qt.thread_view import QtThreadView
from toad.thread_identity import ThreadIdentity


@dataclass(frozen=True)
class _FakeChoice:
    value: str
    name: str
    description: str | None = None


def _qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app


def test_provider_choice_selection_marks_cross_provider_switches_as_forks() -> None:
    advertised: tuple[ModelChoice, ...] = (
        _FakeChoice("anthropic/claude-sonnet-4-5", "Claude Sonnet 4.5", "Anthropic"),
        _FakeChoice("anthropic/claude-opus-4-6", "Claude Opus 4.6", "Anthropic"),
        _FakeChoice("openai-codex/gpt-5.6-sol", "GPT-5.6 Sol", "OpenAI Codex"),
    )
    merged = merge_provider_model_choices(advertised)
    merged_values = {c.value for c in merged}
    assert "anthropic/claude-opus-4-6" in merged_values
    assert "openai-codex/gpt-5.6-sol" in merged_values
    # Generic provider-driven catalog includes declared providers & CLI inbox automatically.
    assert "antigravity/gemini-4-neon" in merged_values
    assert CliInboxSelection.wire_value in merged_values

    class _ProbeSelection(ProviderChoiceSelection):
        def __init__(self) -> None:
            self.init_model_selection()

        def provider_choices(self):
            return merged

        def provider_current(self) -> str:
            return "anthropic/claude-sonnet-4-5"

        @property
        def selection_active(self) -> bool:
            return True

        def select_model(self, model_id: str) -> None:
            del model_id

        def connect_provider(self) -> None:
            return None

        def search_query(self) -> str:
            return ""

        def highlighted_model_id(self) -> str | None:
            return None

        def present_filtered_models(self, ranked, highlighted_index, summary) -> None:
            del ranked, highlighted_index, summary

    ranked, _summary = _ProbeSelection().rank_models("")
    by_value = {entry.choice.value: entry for entry in ranked}

    assert by_value["anthropic/claude-sonnet-4-5"].is_current is True
    assert by_value["anthropic/claude-sonnet-4-5"].will_fork is False
    assert "↪ forks" not in by_value["anthropic/claude-sonnet-4-5"].plain_label

    assert by_value["anthropic/claude-opus-4-6"].will_fork is False
    assert "↪ forks" not in by_value["anthropic/claude-opus-4-6"].plain_label

    assert by_value["openai-codex/gpt-5.6-sol"].will_fork is True
    assert "↪ forks" in by_value["openai-codex/gpt-5.6-sol"].plain_label

    assert by_value["antigravity/gemini-4-neon"].will_fork is True
    assert "↪ forks" in by_value["antigravity/gemini-4-neon"].plain_label

    assert by_value[CliInboxSelection.wire_value].will_fork is False
    assert "↪ forks" not in by_value[CliInboxSelection.wire_value].plain_label


def test_qt_provider_model_dialog_and_unified_thread_view_fork(tmp_path: Path) -> None:
    _qt_app()
    host = QWidget()

    # 1. Both QtAcpSessionView and QtMailboxView inherit focus_model_choice from QtThreadView.
    for member in ("focus_model_choice", "_model_dialog_finished"):
        assert member not in vars(QtAcpSessionView)
        assert member not in vars(QtMailboxView)
        assert getattr(QtAcpSessionView, member) is getattr(QtThreadView, member)
        assert getattr(QtMailboxView, member) is getattr(QtThreadView, member)

    # 2. QtModelChoiceDialog.for_provider_catalog renders provider-driven choices & fork badges.
    advertised = (
        _FakeChoice("anthropic/claude-opus-4-6", "Claude Opus 4.6", "Anthropic"),
        _FakeChoice("openai-codex/gpt-5.6-sol", "GPT-5.6 Sol", "OpenAI Codex"),
    )
    dialog = QtModelChoiceDialog.for_provider_catalog(
        lambda: merge_provider_model_choices(advertised),
        lambda: "anthropic/claude-opus-4-6",
        "test-scope",
        parent=host,
    )
    assert isinstance(dialog.selection, QtProviderModelSelection)
    dialog.selection.open_selection()
    labels = [
        dialog.selection.option_list.item(i).text()
        for i in range(dialog.selection.option_list.count())
    ]
    assert any("Claude Opus 4.6" in label and label.startswith("✓ ") for label in labels)
    assert any("GPT-5.6 Sol" in label and "↪ forks" in label for label in labels)
    assert any("Gemini 4 Neon" in label and "↪ forks" in label for label in labels)
    dialog.selection.search_input.setText("antigravity")
    filtered = [
        dialog.selection.option_list.item(i).text()
        for i in range(dialog.selection.option_list.count())
    ]
    assert filtered and all("antigravity/" in label for label in filtered)
    dialog.close()
    host.close()

    # 3. QtThreadView.apply_thread_model_choice converts cross-provider switches into Core forks.
    comms = Comms(CommsRoute(tmp_path / "comms"))
    comms.registry.declare(
        NativeThread(
            "architect",
            frozenset({"comms"}),
            Checkout(tmp_path),
            model=DeclaredModel("anthropic/claude-opus-4-6"),
        ),
        StoppedThreadStatus(),
    )
    incarnation: ThreadIncarnation = comms.registry.require("architect").incarnation

    class _LocalCore:
        def call(self, request):
            return ServedRequest.serving(request).apply_without_thread(comms, HumanCaller())

    flashes: list[str] = []

    class _ProbeThreadView:
        thread_identity = ThreadIdentity(incarnation, str(comms.root))
        app = SimpleNamespace(
            coordination_access=SimpleNamespace(
                open_current=lambda: SimpleNamespace(core=_LocalCore())
            )
        )

        def flash_success(self, text: str) -> None:
            flashes.append(text)

        def flash_error(self, text: str) -> None:
            flashes.append(f"ERR:{text}")

    result = asyncio.run(
        QtThreadView.apply_thread_model_choice(
            _ProbeThreadView(),  # type: ignore[arg-type]
            "openai-codex/gpt-5.6-sol",
        )
    )
    assert result is not None
    assert result.forked_from == "architect"
    assert result.thread == "architect-openai-codex"
    assert any("Forked architect → architect-openai-codex" in msg for msg in flashes)

    # Parent thread stays on Anthropic; forked child runs OpenAI Codex with ForkedParent lineage.
    assert comms.registry.require("architect").model == DeclaredModel("anthropic/claude-opus-4-6")
    forked = comms.registry.require("architect-openai-codex")
    assert forked.model == DeclaredModel("openai-codex/gpt-5.6-sol")
    assert forked.parent == ForkedParent("architect")
    assert ModelSelection.crosses_provider_values(
        "anthropic/claude-opus-4-6", "openai-codex/gpt-5.6-sol"
    )
