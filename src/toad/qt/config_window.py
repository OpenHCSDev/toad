"""OpenHCS-blueprint ``pyqt_reactive.ConfigWindow`` host for Toad and Core agent settings.

Mirrors OpenHCS's ``OpenHCSConfigWindow``: one thin ``ConfigDocumentFormat`` backed by
``FieldCodec`` JSON and one ``ToadConfigWindow(ConfigWindow)`` subclass that renders
``ToadSettings``, scoped ``AgentSettingsConfig`` layers, and ``Thread`` subclass configs
(``LazyThreadSettings`` / ``LazyCliInboxSettings``) with live cross-scope inheritance,
provenance, hierarchy navigation, reset-to-inherited, and View Code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.nominal.field_codec import FieldCodec
from PySide6.QtWidgets import QWidget
from pyqt_reactive.theming.color_scheme import ColorScheme
from pyqt_reactive.windows.config_window import (
    ConfigDocumentFormat,
    ConfigSaveParticipant,
    ConfigWindow,
    ConfigWindowTabSpec,
)

from toad.client.agent_settings_state import AgentSettingsChain


class ToadConfigDocument(ConfigDocumentFormat):
    """JSON source document format for Toad and Core ``FieldCodec`` config records."""

    def render(self, config: object, *, expected_config_type: type, clean_mode: bool) -> str:
        del expected_config_type, clean_mode
        return json.dumps(FieldCodec.encode(config), indent=2, sort_keys=True)

    def from_source(self, source: str, *, expected_config_type: type) -> object:
        return FieldCodec.decode(expected_config_type, json.loads(source))


@dataclass(frozen=True, slots=True)
class ScopedConfigTabSpec(ConfigWindowTabSpec):
    """``ConfigWindowTabSpec`` labelled by its ``ObjectState.scope_label``."""

    @property
    def label(self) -> str:
        return self.state.scope_label


class ToadConfigWindow(ConfigWindow):
    """``pyqt_reactive.ConfigWindow`` specialized for Toad and Core agent settings."""

    document_format: ClassVar[ConfigDocumentFormat] = ToadConfigDocument()

    @classmethod
    def for_agent_settings(
        cls,
        chain: AgentSettingsChain,
        *,
        color_scheme: ColorScheme | None = None,
        parent: QWidget | None = None,
        title_text: str | None = None,
    ) -> ToadConfigWindow:
        """Open a multi-tab ``ConfigWindow`` across ``chain``'s scopes and thread config."""
        tabs: list[ConfigWindowTabSpec] = [
            ScopedConfigTabSpec(state=chain.state_for(scope))
            for scope in chain.scopes
        ]
        if chain.thread_config_state is not None:
            tabs.append(ScopedConfigTabSpec(state=chain.thread_config_state))
        target_scope = chain.scopes[-1]
        default_title = f"Agent Settings · {target_scope.label}"
        if chain.thread_class is not None:
            default_title = f"{default_title} ({chain.thread_class.tab_kind_label})"
        window = cls(
            tabs=tuple(tabs),
            color_scheme=color_scheme,
            parent=parent,
            scope_id=chain.state_for(target_scope).scope_id,
            title_text=title_text or default_title,
        )
        window.resize(980, 720)
        return window


__all__ = [
    "ConfigSaveParticipant",
    "ConfigWindowTabSpec",
    "ToadConfigDocument",
    "ToadConfigWindow",
]
