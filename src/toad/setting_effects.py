"""Preference effects, referenced by the declarations that own them."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.setting_choices import Scrollbar, SessionBar, ThemeChoice


def column(app: ToadApp, value: bool) -> None:
    app.column = value


def column_width(app: ToadApp, value: int) -> None:
    app.column_width = value


def theme(app: ToadApp, value: type[ThemeChoice]) -> None:
    app.theme = value.theme.name


def scrollbar(app: ToadApp, value: type[Scrollbar]) -> None:
    app.scrollbar = value.declared_name


def compact_input(app: ToadApp, value: bool) -> None:
    app.set_class(value, "-compact-input")


def footer(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-footer")


def status_line(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-status-line")


def agent_title(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-agent-title")


def info_bar(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-info-bar")


def thoughts(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-thoughts")


def sessions_bar(app: ToadApp, value: type[SessionBar]) -> None:
    app.update_show_sessions()
