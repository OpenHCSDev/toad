"""Polymorphic OpenHCS ``formbridge`` flash + ``AbstractManager`` tests for Textual & Qt."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from agent_comms.execution.pi_vocabulary import LowThinkingLevel
from agent_comms.registry.agent_settings import AgentSettings
from agent_comms.registry.agent_settings_wire import (
    ChannelSettingsScope,
    ProjectSettingsScope,
    ThreadSettingsScope,
)
from formbridge.animation.flash_coordinator import FlashCoordinator
from formbridge.managers.abstract_manager import AbstractManager
from formbridge.managers.item_hooks import AttributeItemIdProjection, ManagerItemHooks
from formbridge.managers.state_binding import ManagerStateBinding
from formbridge.managers.workflows import ManagerDeletionWorkflow
from objectstate import set_base_config_type
from PySide6.QtWidgets import QApplication
from textual.app import ComposeResult
from ui_theme.catalog import SCHEMES

from toad.client.agent_settings_state import AgentSettingsChain
from toad.client.form_flash import FormFlashSurface
from toad.forms.abstract_manager import TextualAbstractManagerWidget
from toad.forms.flash_surface import TextualFlashSurface
from toad.forms.object_configuration import ObjectFormView
from toad.markdown_links import LinkContext
from toad.patch import DiffSettings
from toad.preferences import ToadSettings
from toad.qt.flash_surface import QtFlashSurface
from toad.qt.forms import QtObjectFormView
from toad.qt.lines import QtLineRenderer
from toad.textual_colours import ThemedApp


@dataclass
class _ManagedRecord:
    item_id: str
    title: str
    scope_id: str
    threshold: int = 1

    def __str__(self) -> str:
        return self.title


class _DeleteManagedRecords(ManagerDeletionWorkflow):
    def validate(self, items: list[Any]) -> bool:
        return not any(item.item_id == "locked" for item in items)

    def delete(self, items: list[Any]) -> None:
        self.deleted.extend(item.item_id for item in items)

    def __init__(self) -> None:
        self.deleted: list[str] = []


class _SampleTextualManager(TextualAbstractManagerWidget):
    TITLE = "Sample manager"
    ITEM_NAME_SINGULAR = "record"
    ITEM_NAME_PLURAL = "records"
    STATE_BINDING = ManagerStateBinding(
        items_attr="records",
        selection_attr="selected_record_id",
        selection_signal_attr="",
    )
    ITEM_HOOKS = ManagerItemHooks(
        id_projection=AttributeItemIdProjection("item_id"),
    )

    def __init__(self, records: list[_ManagedRecord], **kwargs: Any) -> None:
        self.records = records
        self.selected_record_id = ""
        self.edited: list[str] = []
        self._deletion = _DeleteManagedRecords()
        self.DELETION_WORKFLOW = self._deletion  # type: ignore[misc]
        super().__init__(**kwargs)

    def _compute_scope_for_item(self, item: Any) -> str:
        return item.scope_id

    def show_item_editor(self, item: Any) -> None:
        self.edited.append(item.item_id)


def _qt_app() -> QApplication:
    set_base_config_type(ToadSettings)
    return QApplication.instance() or QApplication([])


def test_qt_object_form_flashes_through_formbridge_coordinator(tmp_path: Path) -> None:
    _qt_app()
    core_settings = AgentSettings.at(tmp_path)
    project_scope = ProjectSettingsScope("agent-comms")
    channel_scope = ChannelSettingsScope("agent-comms", "#comms")
    thread_scope = ThreadSettingsScope("agent-comms", "toad-qt")
    projection = core_settings.projection(thread_scope, channel="#comms")

    chain = AgentSettingsChain(projection, lambda _s, _u: None)
    try:
        thread_state = chain.state_for(thread_scope)
        project_state = chain.state_for(project_scope)
        form = QtObjectFormView.whole(thread_state)
        renderer = QtLineRenderer(SCHEMES[0], LinkContext(None, ()), DiffSettings())
        form.theme(renderer)
        form.body.show()
        form.follow_state()

        assert isinstance(form.flash_surface, QtFlashSurface)
        assert isinstance(form.flash_surface, FormFlashSurface)

        # Cascade an ancestor edit from Project -> Thread: Thread's QtObjectFormView queues a flash!
        project_state.field("thread.thinking_level").edit(LowThinkingLevel)
        coordinator = form.flash_surface.coordinator
        assert coordinator.is_flashing("thread.thinking_level")

        # Advance the shared FlashCoordinator through fade-in, peak admission, hold, fade-out, complete.
        t0 = coordinator._playbacks["thread.thinking_level"].phase_started_at
        active = coordinator.step(now=t0 + 0.05)
        assert "thread.thinking_level" in active
        assert "rgba(" in form.values["thread.thinking_level"].widget.styleSheet()

        coordinator.step(now=t0 + 0.25)  # peak alpha=255 admitted -> enters HoldPhase
        coordinator.step(now=t0 + 0.35)  # HoldPhase -> FadeOutPhase
        coordinator.step(now=t0 + 1.50)  # FadeOutPhase -> CompletePhase
        assert not coordinator.is_flashing("thread.thinking_level")
        assert form.values["thread.thinking_level"].widget.styleSheet() == ""

        form.leave_state()
    finally:
        chain.close()


@pytest.mark.asyncio
async def test_textual_object_form_and_abstract_manager_use_formbridge(tmp_path: Path) -> None:
    set_base_config_type(ToadSettings)
    core_settings = AgentSettings.at(tmp_path)
    project_scope = ProjectSettingsScope("agent-comms")
    channel_scope = ChannelSettingsScope("agent-comms", "#comms")
    thread_scope = ThreadSettingsScope("agent-comms", "toad-qt")
    projection = core_settings.projection(thread_scope, channel="#comms")
    chain = AgentSettingsChain(projection, lambda _s, _u: None)

    project_state = chain.state_for(project_scope)
    channel_state = chain.state_for(channel_scope)
    thread_state = chain.state_for(thread_scope)

    rec1 = _ManagedRecord("r1", "Channel #comms", channel_state.scope_id)
    rec2 = _ManagedRecord("r2", "Thread toad-qt", thread_state.scope_id)

    clock_now = 100.0
    mgr_coordinator = FlashCoordinator(clock=lambda: clock_now)

    class _HarnessApp(ThemedApp[None]):
        def __init__(self) -> None:
            super().__init__()
            self.manager = _SampleTextualManager([rec1, rec2], flash_coordinator=mgr_coordinator)
            self.form = ObjectFormView.whole(thread_state)

        def compose(self) -> ComposeResult:
            yield self.manager
            yield self.form

    try:
        app = _HarnessApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()

            # 1. TextualAbstractManagerWidget inherits AbstractManager directly and drives selection,
            #    activation, deletion, dirty-field indicators, and TextualFlashSurface cohorts.
            assert isinstance(app.manager, AbstractManager)
            assert isinstance(app.manager.flash_surface, TextualFlashSurface)
            assert app.manager.list_surface().row_count() == 2

            app.manager.select_item_id("r2")
            await pilot.pause()
            assert [item.item_id for item in app.manager.selected_items()] == ["r2"]

            app.manager.edit_selected()
            assert app.manager.edited == ["r2"]

            # Direct edit on Channel updates dirty marker; Project ancestor cascade fires
            # ManagerScopeVisualTracker._on_registry_resolved_changed -> coalesced flash cohort
            # across BOTH the Textual manager rows AND Textual ObjectFormView!
            channel_state.field("rule_gate.owner_prompts").edit(5)
            await pilot.pause()
            assert "rule_gate.owner_prompts" in app.manager.dirty_fields_for(rec1)
            assert "●" in app.manager._scope_rows[rec1.scope_id]._label_text

            project_state.field("thread.thinking_level").edit(LowThinkingLevel)
            await pilot.pause()
            assert mgr_coordinator.is_flashing(rec1.scope_id)
            assert mgr_coordinator.is_flashing(rec2.scope_id)

            clock_now = 100.05
            active = mgr_coordinator.step(now=clock_now)
            assert rec1.scope_id in active
            assert app.manager._scope_rows[rec1.scope_id].styles.background.a > 0

            clock_now = 100.25
            mgr_coordinator.step(now=clock_now)  # peak alpha=255 admitted -> HoldPhase
            clock_now = 100.35
            mgr_coordinator.step(now=clock_now)  # HoldPhase -> FadeOutPhase
            clock_now = 101.50
            mgr_coordinator.step(now=clock_now)  # FadeOutPhase -> CompletePhase
            assert not mgr_coordinator.is_flashing(rec1.scope_id)

            # Deletion workflow runs through formbridge ManagerActionController.
            app.manager.delete_selected()
            assert app.manager._deletion.deleted == ["r2"]

            # 2. Textual ObjectFormView flashed on the exact same Project -> Thread cascade!
            assert isinstance(app.form.flash_surface, TextualFlashSurface)
            form_coord = app.form.flash_surface.coordinator
            assert form_coord.is_flashing("thread.thinking_level")
            ft0 = form_coord._playbacks["thread.thinking_level"].phase_started_at
            active_form = form_coord.step(now=ft0 + 0.05)
            assert "thread.thinking_level" in active_form
            assert app.form.values["thread.thinking_level"].styles.background.a > 0
            form_coord.step(now=ft0 + 0.25)
            form_coord.step(now=ft0 + 0.35)
            form_coord.step(now=ft0 + 1.50)
            assert not form_coord.is_flashing("thread.thinking_level")
    finally:
        chain.close()
