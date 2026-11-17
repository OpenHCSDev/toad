"""Toolkit-neutral sidebar panel metadata.

`PanelSpec` carries the identity + layout fields both frontends need to describe
a panel: `title` (which doubles as the key under which `SidebarState.panels_collapsed`
stores the panel's collapsed state), `flex` (whether the panel keeps room to
grow into on open), the default `collapsed` state used at first mount, and a
stable `id` for CSS/testing selectors. None of these fields carry widget
references, so the spec imports from either frontend. Each frontend subclasses
this and attaches its own widget reference — Textual's `SideBar.Panel` adds
`widget`/`header_control`, Qt's analog holds a `QWidget`.

Keeping the identity fields in one place means both frontends address the same
panel by the same key when they read/write `SidebarState.panels_collapsed` via
its `is_panel_collapsed` / `set_panel_collapsed` accessors — one authority for
whether a panel is open, so the two frontends can never disagree about its state.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PanelSpec:
    title: str
    flex: bool = False
    collapsed: bool = False
    id: str | None = None
