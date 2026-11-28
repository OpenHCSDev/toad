"""Toolkit-neutral family of the panels the thread sidebar shows. Both Textual's
`SessionPanel` family (`widgets/session_thread_panels.py`) and Qt's `ThreadSettingsPane`
(`qt/placement.py`) derive their roster directly from `ThreadSidebarPanel`, so a new panel
added here appears on both frontends automatically — no hand-rolled tuple, no string keys.

Each frontend renders a panel through a class inheriting `ThreadSidebarPanelBody`, naming
its `panel_type` class directly. Qt composes every member of `ThreadSidebarPanel` from its
bodies and fails loud on a member with none.
"""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from metaclass_registry import AbstractHooksMeta

from toad.client.sidebar_panels import PanelSpec


class ThreadSidebarPanel(DeclaredFamily, affix="SidebarPanel"):
    """One thread-sidebar panel's toolkit-neutral identity. Declaration order is display order."""

    heading: ClassVar[str]
    panel_id: ClassVar[str | None] = None
    collapsed: ClassVar[bool] = False
    flex: ClassVar[bool] = False

    @classmethod
    def panel_spec(cls) -> PanelSpec:
        """The collapsible panel both sidebars frame this entry in: its heading keys the
        sidebar's shared `SidebarState`, as Textual's `SessionPanel.compose_panel` keys it."""
        return PanelSpec(
            title=cls.heading,
            flex=cls.flex,
            collapsed=cls.collapsed,
            id=cls.panel_id or f"{cls.declared_name}-panel",
        )


class DmSidebarPanel(ThreadSidebarPanel, declared_name=None):
    """Panels shown in DM / conversation views as well as session views."""


class CoordinationSidebarPanel(DmSidebarPanel):
    heading = "Coordination"


class CommsSidebarPanel(DmSidebarPanel):
    heading = "Comms"


class PlanSidebarPanel(ThreadSidebarPanel):
    heading = "Plan"
    collapsed = True


class ProjectSidebarPanel(ThreadSidebarPanel):
    heading = "Project"
    collapsed = True
    flex = True


class ContextSidebarPanel(ThreadSidebarPanel):
    heading = "Context"


class ThreadSidebarPanelBody:
    """One thread-sidebar panel as a frontend renders it: Textual's `SessionPanel` family and
    each Qt panel widget inherit this. The class names its `ThreadSidebarPanel` member by
    `panel_type`, and that member owns the heading, id, collapsed and flex defaults both read."""

    panel_type: ClassVar[type[ThreadSidebarPanel]]

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "panel_type" in vars(cls):
            panel_type = cls.panel_type
            if panel_type not in ThreadSidebarPanel.members_with(ThreadSidebarPanel):
                raise TypeError(f"{cls.__qualname__}.panel_type must be a concrete ThreadSidebarPanel member, got {panel_type!r}")

    @classmethod
    def panel_spec(cls) -> PanelSpec:
        return cls.panel_type.panel_spec()


class ThreadSidebarContents[Entry](metaclass=AbstractHooksMeta):
    """What the thread sidebar lists, in order: the roster's panels, the viewed object's
    right-click actions (`ViewActionsPanel`), then each of the viewed object's own settings
    (`ViewSettingsOwner.configuration_fields`). Textual's `ThreadSidebar` and Qt's
    `ThreadSettingsPane` both inherit this, so a setting or action declared once is an entry
    on both, after the same roster."""

    @abstractmethod
    def roster_entries(self) -> Iterable[Entry]:
        """The roster's panels, as this frontend draws them."""

    @abstractmethod
    def action_entries(self, view) -> Iterable[Entry]:
        """The viewed object's right-click actions panel, as this frontend draws it."""

    @abstractmethod
    def agent_settings_entries(self, view) -> Iterable[Entry]:
        """The viewed object's scoped Core agent settings panel, as this frontend draws it."""

    @abstractmethod
    def setting_entries(self, view) -> Iterable[Entry]:
        """One entry per setting ``view`` lists, as this frontend draws it."""

    def thread_entries(self, view) -> tuple[Entry, ...]:
        return (
            *self.roster_entries(),
            *self.action_entries(view),
            *self.agent_settings_entries(view),
            *self.setting_entries(view),
        )
