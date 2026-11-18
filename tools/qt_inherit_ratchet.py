"""Fail when a Qt class re-implements a frontend-neutral or Textual sibling instead of inheriting it.

A Qt class `QtFoo` (or `Foo`) under toad.qt whose same-named sibling `Foo` lives elsewhere in toad
must share a toolkit-neutral toad ancestor with it — the behaviour lives once, on that ancestor,
and the Qt class adds only toolkit calls. A pair sharing nothing is a hand-rolled parallel copy.

KNOWN_COPIES is the debt on main when this ratchet landed. It only shrinks:
  - a NEW copy (not listed) fails: hoist the shared behaviour and inherit it instead;
  - a listed copy that now shares an ancestor also fails until you delete its line here.
A second rule: every class under toad.qt inherits at least one frontend-neutral toad
ancestor, or is listed in QT_ONLY with the toolkit-only fact that keeps it out of the shared
code. KNOWN_BARE is the bare debt when that rule landed; like KNOWN_COPIES it only shrinks.
Run with an interpreter that has PySide6 (the agent-comms runtime):
  QT_QPA_PLATFORM=offscreen PYTHONPATH=src <runtime>/bin/python tools/qt_inherit_ratchet.py
Every Qt PR pastes this tool's output.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys

KNOWN_COPIES = {
}

# Pairs whose names differ, checked by the same shared-ancestor rule: a Qt class and the
# Textual class it draws the same thing as. A pair still sharing nothing belongs in
# KNOWN_COPIES. The channels-sidebar pairs guard the earlier sidebar parity work.
EXPLICIT_PAIRS = {
    # thread (view-settings) sidebar
    "toad.qt.placement.ThreadSettingsPane": "toad.widgets.side_bar.ThreadSidebar",
    "toad.qt.sidebar_panel.QtPanelMenu": "toad.widgets.side_bar.PanelMenu",
    "toad.qt.sidebar_panel.QtSidebarPanelFrame": "toad.widgets.side_bar.SideBarCollapsible",
    "toad.qt.sidebar_panel.QtSidebarPanels": "toad.widgets.sidebar_viewport.SidebarViewport",
    "toad.qt.placement.QtObjectProperties": "toad.configured_view.ObjectProperties",
    "toad.qt.coordination_panel.QtCoordinationStatus": "toad.widgets.comms_sidebar.CoordinationStatus",
    "toad.qt.thread_comms_panel.QtThreadCommsPanel": "toad.widgets.thread_comms.ThreadCommsSidebar",
    "toad.qt.thread_comms_panel.QtRelationshipSort": "toad.widgets.thread_comms.RelationshipSort",
    "toad.qt.plan_panel.QtPlan": "toad.widgets.plan.Plan",
    "toad.qt.project_panel.QtProjectPanel": "toad.widgets.project_panel.ProjectPanel",
    "toad.qt.context_panel.QtContextExplorer": "toad.widgets.context_explorer.ContextExplorer",
    "toad.qt.session_panel.SessionPanel": "toad.widgets.session_thread_panels.SessionPanel",
    "toad.qt.sidebar_panel.QtSidebarSearch": "toad.widgets.side_bar.SidebarSearch",
    "toad.qt.window.ConversationView": "toad.widgets.conversation.Conversation",
    "toad.qt.thread_view.QtThreadView": "toad.widgets.conversation.Conversation",
    # channels sidebar and chrome (regression guards)
    "toad.qt.side_bar.QtWorkspaceChrome": "toad.workspace_chrome.WorkspaceChrome",
    "toad.qt.side_bar.QtSideBar": "toad.widgets.side_bar.SideBar",
    "toad.qt.side_bar.QtSideBarToggle": "toad.widgets.side_bar.SideBarToggle",
    "toad.qt.side_bar.QtSidebarSlider": "toad.widgets.side_bar.SidebarSlider",
    "toad.qt.side_bar.QtSidebarAction": "toad.widgets.side_bar.SidebarAction",
    "toad.qt.side_bar.QtSidebarResizeHandle": "toad.widgets.side_bar.SidebarResizeHandle",
    "toad.qt.channel_sort.QtChannelListSort": "toad.widgets.session_sort.ChannelListSort",
    "toad.qt.channel_sort.QtChannelSortControl": "toad.widgets.comms_sidebar.ChannelSortChoice",
    "toad.qt.window.NewSessionRow": "toad.widgets.comms_sidebar.NewSessionButton",
    "toad.qt.window.QtStartSessionButton": "toad.screens.welcome.StartSessionButton",
}

# Same name, different concept: not a frontend pair. Each entry says what the sibling really is.
NOT_SIBLINGS = {
    "toad.qt.sidebar_panel.QtSidebarPanels": "toad.widgets.side_bar.SidebarPanels is the panels' hydration-state family (Absent/Scheduled/Loaded), not a panel column",
    "toad.qt.plan_panel.QtPlan": "toad.core.events.Plan is Core's plan event, not a panel",
    "toad.qt.goal.QtGoalControl": "toad.slash_command.GoalControl is the /goal slash command, not a widget",
    "toad.qt.window.QtSessionEntry": "toad.client.session_entry.SessionEntry is the session record; QtSessionEntry is a SessionEntries member",
    "toad.qt.prompt_stack.QtFlash": "toad.messages.Flash is the Textual Message requesting a flash; the widget sibling toad.widgets.flash.Flash shares toad.client.prompt_stack.FlashNotice",
    "toad.qt.prompt_stack.QtSessionDetails": "toad.client.session_tracker.SessionDetails is the tab's session record; the widget sibling toad.widgets.session_details.SessionDetails shares ObservedActivity + SessionStatusTitle",
}

QT_ONLY = {
    'toad.qt.android.SessionRecord': 'Android process lifecycle: Android kills a backgrounded app and destroys its activity without telling the process, so the next start reads this record',
    'toad.qt.android.SuspendedMemory': "Android suspend: bionic's M_PURGE returns freed allocator memory to the system",
    'toad.qt.history.HistoryRows': "QAbstractListModel exposing the shared fragments to Qt's list view; Textual has no item model",
    'toad.qt.history.SourceTask': "an asyncio.Task on qasync's Qt event loop with the pager's wait() join; Textual runs workers",
    'toad.qt.host.ScreenWideWindow': "a Qt top-level window clamped to the Android screen's available width (screen less system bars)",
    'toad.qt.metrics.UiGap': 'Qt pixel spacing tokens; Textual spaces in cells through its CSS',
    'toad.qt.window.HeldRowMenu': "Qt TapAndHold gesture and context-menu event filter on the tree's viewport; the entries come from each row's shared menu_entries",
    'toad.qt.window.SwallowsRelease': 'a Qt event filter that eats the one mouse release ending a held finger, so the hold does not also tap the row',
}

KNOWN_BARE = frozenset({
    'toad.qt.activity.ActivityLine',
    'toad.qt.activity.ActivitySweep',
    'toad.qt.command_form.CommandApply',
    'toad.qt.composer.CommandOffer',
    'toad.qt.composer.ComposerEditor',
    'toad.qt.composer.MentionOffer',
    'toad.qt.composer.Offer',
    'toad.qt.composer_vim.ComposerVimMode',
    'toad.qt.goal.GoalPress',
    'toad.qt.history.HistoryRowDelegate',
    'toad.qt.history.NoTask',
    'toad.qt.history.QtTopRow',
    'toad.qt.keymap_screen._KeymapSave',
    'toad.qt.main.QtClientSettings',
    'toad.qt.menu.QtMenuRow',
    'toad.qt.page.Page',
    'toad.qt.paste_profile.QtProfilePastePanel',
    'toad.qt.sidebar_panel.QtPanelEntry',
    'toad.qt.sidebar_panel.QtSidebarShell',
    'toad.qt.team_board_screen.QtTeamMemberView',
    'toad.qt.thinking_animator.QtThinkingAnimator',
    'toad.qt.window.ApplicationKeys',
    'toad.qt.window.BusLabel',
    'toad.qt.window.BusRow',
    'toad.qt.window.CommandRead',
    'toad.qt.window.ConversationRow',
    'toad.qt.window.ConversationRows',
    'toad.qt.window.HeaderLineControl',
    'toad.qt.window.ListedFailure',
    'toad.qt.window.ListedModel',
    'toad.qt.window.MenuActionRun',
    'toad.qt.window.OpenSection',
    'toad.qt.window.SidebarItem',
    'toad.qt.window.SidebarSection',
    'toad.qt.window.StatusSection',
    'toad.qt.window.UnavailableSection',
    'toad.qt.window.WelcomeContent',
})

FRONTEND_PREFIXES = ("toad.qt", "toad.widgets", "toad.screens")


def neutral(cls: type) -> bool:
    """A toad class that belongs to neither frontend: where shared behaviour lives."""
    return cls.__module__.startswith("toad.") and not cls.__module__.startswith(FRONTEND_PREFIXES)


def classes_under(package_name: str) -> dict[str, type]:
    package = importlib.import_module(package_name)
    found: dict[str, type] = {}
    for info in pkgutil.walk_packages(package.__path__, package_name + "."):
        module = importlib.import_module(info.name)  # an import failure is a failure, never skipped
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__:
                found[f"{cls.__module__}.{cls.__qualname__}"] = cls
    return found


def copies() -> dict[str, str]:
    everything = classes_under("toad")
    siblings: dict[str, type] = {}
    for path, cls in everything.items():
        if not path.startswith("toad.qt."):
            siblings.setdefault(cls.__name__, cls)
    pairs: dict[str, str] = {}
    for path, cls in everything.items():
        if not path.startswith("toad.qt."):
            continue
        sibling = siblings.get(cls.__name__.removeprefix("Qt"))
        if sibling is None or path in NOT_SIBLINGS:
            continue
        if not shares_neutral(cls, sibling):
            pairs[path] = f"{sibling.__module__}.{sibling.__qualname__}"
    for path, sibling_path in EXPLICIT_PAIRS.items():
        cls, sibling = everything[path], everything[sibling_path]  # a renamed class fails here
        if not shares_neutral(cls, sibling):
            pairs[path] = sibling_path
    return pairs


def shares_neutral(cls: type, sibling: type) -> bool:
    return any(neutral(ancestor) for ancestor in cls.__mro__ if ancestor in sibling.__mro__)


def bare() -> frozenset[str]:
    """Qt classes inheriting no frontend-neutral toad ancestor and not declared Qt-only."""
    everything = classes_under("toad")
    for path in QT_ONLY:
        everything[path]  # a renamed or deleted Qt-only class fails here
    return frozenset(path for path, cls in everything.items()
                     if path.startswith("toad.qt.") and path not in QT_ONLY
                     and not any(neutral(ancestor) for ancestor in cls.__mro__[1:]))


def main() -> int:
    found_bare = bare()
    new_bare = sorted(found_bare - KNOWN_BARE)
    rooted = sorted(KNOWN_BARE - found_bare)
    for path in new_bare:
        print(f"NEW BARE   {path} inherits no shared toad behaviour: inherit its owner, or declare it in QT_ONLY with the toolkit-only fact")
    for path in rooted:
        print(f"ROOTED     {path} now inherits shared behaviour (or is gone): delete its KNOWN_BARE line")
    print(f"bare Qt classes: {len(found_bare)} (ratchet baseline {len(KNOWN_BARE)}); Qt-only: {len(QT_ONLY)}")
    found = copies()
    new = sorted(set(found) - set(KNOWN_COPIES))
    fixed = sorted(set(KNOWN_COPIES) - set(found))
    for path in new:
        print(f"NEW COPY   {path} re-implements {found[path]}: hoist its behaviour to a shared ancestor and inherit it")
    for path in fixed:
        print(f"FIXED      {path} now shares an ancestor (or is gone): delete its KNOWN_COPIES line")
    print(f"parallel copies: {len(found)} (ratchet baseline {len(KNOWN_COPIES)})")
    return 1 if new or fixed or new_bare or rooted else 0


if __name__ == "__main__":
    sys.exit(main())
