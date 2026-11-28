"""Scoped Core agent settings (Global -> Project -> [Channel] -> Thread) over ObjectState."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_comms.execution.pi_vocabulary import LowThinkingLevel, ServiceTier
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.agent_settings import AgentSettings
from agent_comms.registry.agent_settings_wire import (
    AgentSettingsScope,
    ChannelSettingsScope,
    GlobalSettingsScope,
    ProjectSettingsScope,
    ThreadSettingsScope,
)
from agent_comms.registry.thread_model import DeclaredModel
from agent_comms.team.rule_deal import FullDealMode, RequiredRuleCheckPolicy
from agent_comms.transport.tools.sidebar import (
    CommsAgentSettingsTool,
    CommsSetAgentSettingsTool,
)
from objectstate import ObjectStateRegistry, set_base_config_type
from PySide6.QtWidgets import QApplication

from toad.client.agent_settings_state import (
    AgentSettingsChain,
    AgentSettingsPanel,
    scope_label,
)
from toad.forms.editors import (
    ChoicesEditor,
    EnumEditor,
    IntEditor,
    StructuredEditor,
    ThreadModelEditor,
)
from toad.forms.object_configuration import ObjectFormView
from toad.navigation_target import (
    ChannelTarget,
    DirectTarget,
    FeedTarget,
    NoTarget,
    ThreadTarget,
)
from toad.preferences import ToadSettings
from toad.qt.forms import (
    QtChoicesEditor,
    QtEnumEditor,
    QtIntEditor,
    QtObjectFormView,
    QtStructuredEditor,
    QtThreadModelEditor,
)
from toad.qt.placement import QtAgentSettingsProperties


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    set_base_config_type(ToadSettings)
    return QApplication.instance() or QApplication([])


def test_agent_settings_chain_inheritance_provenance_reset_and_forms(
    qt_app: QApplication, tmp_path: Path
) -> None:
    del qt_app
    core_settings = AgentSettings.at(tmp_path)
    global_scope = GlobalSettingsScope()
    project_scope = ProjectSettingsScope("agent-comms")
    channel_scope = ChannelSettingsScope("agent-comms", "#comms")
    thread_scope = ThreadSettingsScope("agent-comms", "toad-qt")

    core_settings.update_scope(project_scope, {"thread.thinking_level": "low"})
    core_settings.update_scope(channel_scope, {"rule_gate.mode": "full"})
    core_settings.update_scope(thread_scope, {"thread.service_tier": "priority"})

    projection = core_settings.projection(thread_scope, channel="#comms")
    emitted: list[tuple[AgentSettingsScope, dict[str, object]]] = []
    chain = AgentSettingsChain(projection, lambda s, u: emitted.append((s, u)))
    try:
        assert chain.scopes == (global_scope, project_scope, channel_scope, thread_scope)
        thread_state = chain.state_for(thread_scope)

        # Both Qt and Textual render all 10 GlobalAgentSettings fields over the same ObjectState.
        qt_form = QtObjectFormView.whole(thread_state)
        qt_form.follow_state()
        assert len(qt_form.values) == 10
        assert isinstance(qt_form.values["thread.model"].editor, QtThreadModelEditor)
        assert isinstance(qt_form.values["thread.thinking_level"].editor, QtChoicesEditor)
        assert isinstance(qt_form.values["thread.service_tier"].editor, QtEnumEditor)
        assert isinstance(qt_form.values["thread.context_edit_policy"].editor, QtEnumEditor)
        assert isinstance(qt_form.values["rule_gate.mode"].editor, QtChoicesEditor)
        assert isinstance(qt_form.values["rule_gate.owner_prompts"].editor, QtIntEditor)
        assert isinstance(qt_form.values["rule_gate.refresh_remaining"].editor, QtStructuredEditor)

        tui_form = ObjectFormView.whole(thread_state)
        assert len(tui_form.values) == 10
        assert isinstance(tui_form.values["thread.model"].editor, ThreadModelEditor)
        assert isinstance(tui_form.values["thread.thinking_level"].editor, ChoicesEditor)
        assert isinstance(tui_form.values["thread.service_tier"].editor, EnumEditor)
        assert isinstance(tui_form.values["rule_gate.mode"].editor, ChoicesEditor)
        assert isinstance(tui_form.values["rule_gate.owner_prompts"].editor, IntEditor)
        assert isinstance(tui_form.values["rule_gate.refresh_remaining"].editor, StructuredEditor)

        assert thread_state.get_resolved_value("thread.thinking_level") is LowThinkingLevel
        assert thread_state.get_resolved_value("rule_gate.mode") is FullDealMode
        assert thread_state.get_resolved_value("thread.service_tier") is ServiceTier.PRIORITY
        assert qt_form.values["thread.thinking_level"].source.text() == "Inherited from Project agent-comms"
        assert qt_form.values["rule_gate.mode"].source.text() == "Inherited from Channel #comms"
        assert qt_form.values["thread.service_tier"].source.text() == "Override for Thread toad-qt"
        assert qt_form.values["rule_gate.audit"].source.text() == "Built-in default"

        # Edit thread.model -> emits only thread scope and updates provenance live.
        emitted.clear()
        thread_state.field("thread.model").edit(DeclaredModel("anthropic/claude-opus-4-6"))
        assert emitted == [(thread_scope, {"thread.model": "anthropic/claude-opus-4-6"})]
        assert qt_form.values["thread.model"].source.text() == "Override for Thread toad-qt"

        # Reset thread.model -> emits None and falls back to built-in default.
        emitted.clear()
        thread_state.field("thread.model").reset()
        assert emitted == [(thread_scope, {"thread.model": None})]
        assert qt_form.values["thread.model"].source.text() == "Built-in default"

        # Edit Project scope -> emits ONLY Project scope (no spurious child writes) and cascades live.
        emitted.clear()
        project_state = chain.state_for(project_scope)
        project_state.field("rule_gate.audit").edit(RequiredRuleCheckPolicy)
        assert emitted == [(project_scope, {"rule_gate.audit": "required"})]
        assert thread_state.get_resolved_value("rule_gate.audit") is RequiredRuleCheckPolicy
        assert qt_form.values["rule_gate.audit"].source.text() == "Inherited from Project agent-comms"

        qt_form.leave_state()
    finally:
        prefix = chain._prefix
        chain.close()
        assert ObjectStateRegistry.get_by_scope(prefix) is None


def test_qt_agent_settings_panel_round_trip_and_scope_switch(
    qt_app: QApplication, tmp_path: Path
) -> None:
    del qt_app
    core_settings = AgentSettings.at(tmp_path)
    calls: list[object] = []

    class FakeCore:
        def call(self, request):
            calls.append(request)
            if isinstance(request, CommsAgentSettingsTool):
                return core_settings.projection(
                    AgentSettingsScope.parse(request.scope), channel=request.channel
                )
            if isinstance(request, CommsSetAgentSettingsTool):
                return core_settings.update_scope(
                    AgentSettingsScope.parse(request.scope),
                    request.values,
                    channel=request.channel,
                )
            raise AssertionError(f"Unexpected request: {request!r}")

    class ImmediatePreparation:
        async def run_thread(self, work):
            return work()

    class DummyRenderer:
        def themed(self, _widget, callback) -> None:
            callback()

        def theme(self, _colour) -> str:
            return "#88c0d0"

    core = FakeCore()
    app = SimpleNamespace(
        coordination_access=SimpleNamespace(
            observing=lambda _root: SimpleNamespace(core=core),
            open_current=lambda: SimpleNamespace(core=core),
        ),
        preparation=ImmediatePreparation(),
        show_error=lambda error, title: pytest.fail(f"{title}: {error}"),
    )
    view = SimpleNamespace(
        coordination_root=str(tmp_path),
        agent_settings_target=lambda: (ThreadSettingsScope("agent-comms", "toad-qt"), "#comms"),
    )

    async def exercise() -> None:
        panel = QtAgentSettingsProperties(app, view, DummyRenderer())
        await panel.load_agent_settings()
        assert isinstance(calls[-1], CommsAgentSettingsTool)
        assert panel.scope_combo.count() == 4
        assert panel.scope_combo.currentText() == "Thread toad-qt"
        assert panel._form is not None

        # Switch to Project scope and edit thinking_level -> persists to Core and cascades to Thread.
        panel.select_agent_scope(ProjectSettingsScope("agent-comms"))
        assert panel._form is not None
        panel._form.state.field("thread.thinking_level").edit(LowThinkingLevel)
        await asyncio.gather(*tuple(panel._tasks))
        assert isinstance(calls[-1], CommsSetAgentSettingsTool)
        assert calls[-1].scope == "project::agent-comms"
        assert calls[-1].values == {"thread.thinking_level": "low"}

        # Switch back to Thread scope and confirm inherited value + provenance from Core.
        panel.select_agent_scope(ThreadSettingsScope("agent-comms", "toad-qt"))
        assert panel._form.state.get_resolved_value("thread.thinking_level") is LowThinkingLevel
        assert panel._form.values["thread.thinking_level"].source.text() == "Inherited from Project agent-comms"

        prefix = panel._chain._prefix
        panel.release_page()
        assert ObjectStateRegistry.get_by_scope(prefix) is None

    asyncio.run(exercise())


def test_navigation_target_agent_settings_scopes_and_labels() -> None:
    view = SimpleNamespace(
        navigation_context=SimpleNamespace(
            project_path=Checkout(Path("/home/ts/code/projects/agent-comms"))
        )
    )
    assert NoTarget().agent_settings_target(view) == (GlobalSettingsScope(), "")
    assert FeedTarget().agent_settings_target(view) == (GlobalSettingsScope(), "")
    assert ChannelTarget("#comms").agent_settings_target(view) == (
        ChannelSettingsScope("agent-comms", "#comms"),
        "",
    )
    assert ThreadTarget("toad-qt").agent_settings_target(view) == (
        ThreadSettingsScope("agent-comms", "toad-qt"),
        "",
    )
    assert DirectTarget("comms-a").agent_settings_target(view) == (
        ThreadSettingsScope("agent-comms", "comms-a"),
        "",
    )
    assert scope_label(GlobalSettingsScope()) == "Global"
    assert scope_label(ProjectSettingsScope("agent-comms")) == "Project agent-comms"
    assert scope_label(ChannelSettingsScope("agent-comms", "#comms")) == "Channel #comms"
    assert scope_label(ThreadSettingsScope("agent-comms", "toad-qt")) == "Thread toad-qt"
    assert AgentSettingsPanel.panel_spec.title == "Agent settings"
