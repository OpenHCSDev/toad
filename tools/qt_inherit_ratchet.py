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
"Frontend-neutral" means by what a module loads, not only where it sits: a toad module outside
toad.qt/widgets/screens counts as neutral only if importing it, in a fresh interpreter, loads no
toad.widgets/toad.screens module and none of Textual's app/widget/screen/container modules
(#2069 reached Textual's app host from Qt, and the APK build broke). KNOWN_UI_LOADING lists the
modules Qt inherited from that did so when the rule landed, each with its chain; it only shrinks.
A third rule: no toad.qt module imports a toad.widgets/toad.screens module at module level;
KNOWN_QT_FRONTEND_IMPORTS only shrinks.
Run with an interpreter that has PySide6 (the agent-comms runtime):
  QT_QPA_PLATFORM=offscreen PYTHONPATH=src <runtime>/bin/python tools/qt_inherit_ratchet.py
Every Qt PR pastes this tool's output.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import inspect
import json
import pkgutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path

KNOWN_COPIES = {
}

# Pairs whose names differ, checked by the same shared-ancestor rule: a Qt class and the
# Textual class it draws the same thing as. A pair still sharing nothing belongs in
# KNOWN_COPIES. The channels-sidebar pairs guard the earlier sidebar parity work.
EXPLICIT_PAIRS = {
    # the pinned header of the message the reader is in
    "toad.qt.history.QtStickyHeader": "toad.widgets.message_divider.StickyHeader",
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
    "toad.qt.conversation.QtConversation": "toad.widgets.conversation.Conversation",
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
    # channel tree lines (toad.client.sidebar_lines) and the welcome
    "toad.qt.window.SidebarItem": "toad.widgets.sidebar_tree.DetailedRow",
    "toad.qt.window.SidebarSection": "toad.widgets.sidebar_tree.SidebarGroup",
    "toad.qt.window.StatusSection": "toad.sidebar_model_view.SidebarStatus",
    "toad.qt.window.ConversationRow": "toad.widgets.sidebar_tree.CommsRow",
    "toad.qt.window.ConversationRows": "toad.widgets.sidebar_tree.TargetTree",
    "toad.qt.window.HeaderLineControl": "toad.widgets.sidebar_tree.GroupHeaderLine",
    "toad.qt.window.BusRow": "toad.screens.bus_choice.BusOption",
    "toad.qt.window.BusLabel": "toad.widgets.channels_sidebar.SidebarLocationNote",
    "toad.qt.banner.Banner": "toad.widgets.channels_sidebar.SidebarBanner",
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
    'toad.qt.conversation.ComposerPlaceholder': "a Qt composer's place held before it is built: Qt builds a view's widgets in "
        "its constructor, so a composer built there holds the view's first frame (and on Android races the first frame's EGL "
        "setup); Textual composes a screen's widgets and mounts them after its first frame, so it has no placeholder to hold",
    'toad.qt.overlay_scrollbar.OverlayScrollBar': "a QScrollBar floated over a QAbstractScrollArea's viewport, mirroring the area's hidden bar: a terminal cannot draw over its text, so Textual shows `Scrollbar.size` only; the shared fact is `Scrollbar.overlay`",
    'toad.qt.overlay_scrollbar._ViewportGeometry': "an event filter keeping that overlay over the viewport on QEvent.Resize/Move; Textual has no floating child to place",
    'toad.qt.widget_animation.WidgetAnimation': "a clock target's life bound to its Qt widget's C++ lifetime (destroyed signal, shiboken validity); a Textual widget is a Python object the clock can always ask",
    'toad.qt.history.ArrivalFade': "a burst's rows painted at the ARRIVAL cascade's frame as QPainter opacity; Textual paints the same frame into its strips (TranscriptHistory.arrivals_began), and both read the cascade from toad.frame_presentation",
    'toad.qt.action_shortcuts.BoundAction': "a live QShortcut and the action it answers: Qt fires neither of two shortcuts sharing a key (activatedAmbiguously), so ActionKeys keeps each to apply the declared binding order; Textual walks its binding chain itself",
    'toad.qt.splash.QtSplash': "Qt's first frame, painted from Qt and the theme before the client's modules import: a terminal draws Textual's first frame as soon as App.run starts, with the client already imported in the same process, so the TUI has no window to show before its app exists",
    'toad.qt.splash.StepAside': "an application event filter that closes the first frame when Qt shows the client's window: QEvent.Show on a top-level QWidget has no Textual counterpart",
    'toad.qt.android.SessionRecord': 'Android process lifecycle: Android kills a backgrounded app and destroys its activity without telling the process, so the next start reads this record',
    'toad.qt.android.SuspendedMemory': "Android suspend: bionic's M_PURGE returns freed allocator memory to the system",
    'toad.qt.finger_scrolling.FingerScrollGesture': "what a drag on a Qt scroll area's viewport means per platform (QScroller's grab); the terminal scrolls the TUI",
    'toad.qt.finger_scrolling.FingerScrolling': 'a QApplication event filter granting every QAbstractScrollArea the QScroller grab as Qt polishes it; Textual scrolls through the terminal',
    'toad.qt.finger_scrolling.MouseAndWheel': 'the desktop member of FingerScrollGesture: no QScroller grab, so a mouse drag stays a selection',
    'toad.qt.finger_scrolling.TouchAsMouse': "the Android member of FingerScrollGesture: QScroller's LeftMouseButtonGesture on Qt's touch-synthesized mouse",
    'toad.qt.frame_probe.ProbedApplication': "a QApplication whose notify times every Qt event's delivery to its receiver; only a probed run makes it, and Textual has no Qt events",
    'toad.qt.frame_probe.TimedHandles': "times each asyncio callback qasync runs from Qt timer events, naming a slow one's task; part of the Qt probe, which Textual's asyncio loop has no use for",
    'toad.qt.frame_probe.FrameProbe': "measures Qt's own event loop: a QTimer's lateness and Qt key-to-paint latency on the GUI thread; Textual's loop is asyncio's and has no Qt events",
    'toad.qt.history.HistoryRows': "QAbstractListModel exposing the shared fragments to Qt's list view; Textual has no item model",
    'toad.qt.history.PreparedOnFill': "a pyqt-reactive RowFormatting that fills a QTextDocument only when Qt lays a row out; Textual draws line blocks, not documents",
    'toad.qt.client_start.EndRequest': "Qt 6's QEvent.Quit closes every window and leaves qasync's event loop inside one event; this event filter takes the request so the shared client shutdown runs on the loop first. Textual closes its client in App._close_all while its own loop still runs",
    'toad.qt.history.SourceTask': "an asyncio.Task on qasync's Qt event loop with the pager's wait() join; Textual runs workers",
    'toad.qt.float_layer.QtNoticeCard': "one notice drawn as a Qt frame over the page; Textual draws the same notice with its framework's own toast (textual.widgets._toast), and the text, severity and seconds come from the shared host's notify",
    'toad.qt.host.ScreenWideWindow': "a Qt top-level window clamped to the Android screen's available width (screen less system bars)",
    'toad.qt.metrics.UiGap': 'Qt pixel spacing tokens; Textual spaces in cells through its CSS',
    'toad.qt.action_shortcuts.ActionKeys': "Qt has no binding map: it installs a QShortcut per action and sets its keys again when ui.key_mode or ui.keymap changes; Textual's App binds the same catalog keys through its BindingsMap and set_keymap",
    'toad.qt.window.HeldRowMenu': "connects the Qt tree's customContextMenuRequested (a right-click, or a held finger FingerPress delivers as one) to the panel; the entries come from each row's shared menu_entries",
    'toad.qt.finger_press.Press': "one Qt press: the QWidget under it, its global QPointF and whether a touch screen made it, and a tap consumer's claim",
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
    'toad.qt.keymap_screen._KeymapSave',
    'toad.qt.client_start.QtClientSettings',
    'toad.qt.menu.QtMenuRow',
    'toad.qt.page.Page',
    'toad.qt.paste_profile.QtProfilePastePanel',
    'toad.qt.sidebar_panel.QtPanelEntry',
    'toad.qt.sidebar_panel.QtSidebarShell',
    'toad.qt.team_board_screen.QtTeamMemberView',
    'toad.qt.window.ApplicationKeys',
    'toad.qt.window.MenuActionRun',
})

FRONTEND_PREFIXES = ("toad.qt", "toad.widgets", "toad.screens")
# Textual itself ships in the APK and its content, styles and bindings are used toolkit-neutrally;
# what drags a frontend in is Toad's Textual packages and Textual's app/widget/screen chain.
UI_MODULES = ("toad.widgets", "toad.screens", "textual.widgets", "textual.screen", "textual.app",
              "textual.containers")

# Run in a fresh interpreter per module: import it, and report every module that import loaded
# with the module whose import statement loaded it.
PROBE = r"""
import builtins, json, sys
loaded_by = {}
real_import = builtins.__import__
def traced(name, globals=None, locals=None, fromlist=(), level=0):
    importer = (globals or {}).get("__name__", "?")
    before = set(sys.modules)
    try:
        return real_import(name, globals, locals, fromlist, level)
    finally:
        for new in set(sys.modules) - before:
            loaded_by.setdefault(new, importer)
builtins.__import__ = traced
before = set(sys.modules)
__import__(sys.argv[1])
print(json.dumps({name: loaded_by.get(name) for name in set(sys.modules) - before}))
"""


def ui_module(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in UI_MODULES)


def ui_chain(module: str) -> tuple[str, ...]:
    """The import chain from `module` to the first frontend UI module importing it loads, measured
    as the sys.modules delta of a fresh interpreter; () when it loads none."""
    result = subprocess.run([sys.executable, "-c", PROBE, module], capture_output=True, text=True,
                            timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(f"importing {module} failed:\n{result.stderr[-2000:]}")
    loaded_by: dict[str, str | None] = json.loads(result.stdout.strip().splitlines()[-1])
    offending = sorted(name for name in loaded_by if ui_module(name))
    if not offending:
        return ()
    chain = [min(offending, key=lambda name: name.count("."))]
    while chain[-1] != module and loaded_by.get(chain[-1]) and len(chain) < 60:
        chain.append(loaded_by[chain[-1]])
    return tuple(reversed(chain))


def source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path("src").rglob("*.py")):
        digest.update(str(path).encode())
        digest.update(path.read_bytes())
    digest.update(PROBE.encode())
    digest.update(repr(UI_MODULES).encode())
    return digest.hexdigest()[:24]


@cache
def ui_chains(modules: frozenset[str]) -> dict[str, tuple[str, ...]]:
    """`ui_chain` for each module, probed in parallel and cached on disk per source tree."""
    store = Path.home() / ".cache" / "toad-qt-ratchet" / f"{source_digest()}.json"
    known: dict[str, list[str]] = json.loads(store.read_text()) if store.exists() else {}
    missing = sorted(modules - set(known))
    with ThreadPoolExecutor(max_workers=8) as pool:
        for module, chain in zip(missing, pool.map(ui_chain, missing)):
            known[module] = list(chain)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(known))
    return {module: tuple(known[module]) for module in modules}


# Shared-looking modules (outside toad.qt/widgets/screens) that Qt classes inherit from and whose
# import loads Textual's app or widget chain, when this rule landed; each with its chain. It only
# shrinks: hoist the shared part into a module that loads none, then delete the line.
KNOWN_UI_LOADING: dict[str, str] = {
    'toad.client.block_menu':
        'toad.keymap -> toad.key_modes -> toad.neovim_editing -> textual.app',
    'toad.client.history_rows_view':
        'toad.transcript_publication -> toad.session_scope -> toad.widgets.side_bar -> toad.widgets.comms_menu -> textual.view -> textual.app',
    'toad.client.keymap_browser':
        'toad.key_modes -> toad.neovim_editing -> textual.app',
    'toad.client.prompt_stack':
        'toad.key_modes -> toad.neovim_editing -> textual.app',
    'toad.client.session_sources':
        'toad.transcript_publication -> toad.session_scope -> toad.widgets.side_bar -> toad.widgets.comms_menu -> textual.view -> textual.app',
    'toad.client.thread_binding_dispatch':
        'toad.transcript_publication -> toad.session_scope -> toad.widgets.side_bar -> toad.widgets.comms_menu -> textual.view -> textual.app',
    'toad.client.transcript_fragments':
        'toad.widgets',
    'toad.question_actions':
        'toad.widget_actions -> textual.widgets._text_area -> textual.screen -> textual.widgets._toast -> textual.containers',
    'toad.sidebar_model_view':
        'textual.widgets',
    'toad.view_actions':
        'toad.widget_actions -> textual.widgets._text_area -> textual.screen -> textual.widgets._toast -> textual.containers',
    'toad.widget_view':
        'textual.view -> textual.app',
}

KNOWN_QT_FRONTEND_IMPORTS: dict[str, str] = {
}


def candidate_modules() -> frozenset[str]:
    """Every module outside the frontend packages that a Qt class inherits a class from."""
    return frozenset(
        ancestor.__module__
        for path, cls in classes_under("toad").items() if path.startswith("toad.qt.")
        for ancestor in cls.__mro__[1:]
        if ancestor.__module__.startswith("toad.") and not ancestor.__module__.startswith(FRONTEND_PREFIXES))


def neutral(cls: type) -> bool:
    """A toad class that belongs to neither frontend: where shared behaviour lives. Its module
    is outside toad.qt/widgets/screens, and importing it loads no Textual app or widget chain
    (#2069's Qt transfer dialogs reached Textual's app host, and the APK build broke)."""
    module = cls.__module__
    if not module.startswith("toad.") or module.startswith(FRONTEND_PREFIXES):
        return False
    return module in KNOWN_UI_LOADING or not ui_chains(candidate_modules()).get(module, ())


def qt_frontend_imports() -> dict[str, str]:
    """A toad.qt module's own module-level imports of toad.widgets/toad.screens modules (#2069
    was one: toad.qt.transfer imported the Textual transfer widgets for their request kinds)."""
    found: dict[str, str] = {}
    for info in pkgutil.walk_packages(importlib.import_module("toad.qt").__path__, "toad.qt."):
        tree = ast.parse(Path(importlib.util.find_spec(info.name).origin).read_text())
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(FRONTEND_PREFIXES[1:]):
                found[info.name] = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(FRONTEND_PREFIXES[1:]):
                        found[info.name] = alias.name
    return found


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
    chains = ui_chains(candidate_modules())
    loading = {module: chain for module, chain in chains.items() if chain}
    new_loading = sorted(set(loading) - set(KNOWN_UI_LOADING))
    cleared = sorted(set(KNOWN_UI_LOADING) - set(loading))
    for module in new_loading:
        print(f"NEW UI LOAD {module} is inherited by Qt and its import loads {' -> '.join(loading[module])}: "
              "move the shared part to a module that loads no Textual app or widget chain")
    for module in cleared:
        print(f"CLEARED    {module} no longer loads Textual's app or widget chain: delete its KNOWN_UI_LOADING line")
    print(f"shared-looking modules loading Textual UI: {len(loading)} (ratchet baseline {len(KNOWN_UI_LOADING)})")
    direct = qt_frontend_imports()
    new_direct = sorted(set(direct) - set(KNOWN_QT_FRONTEND_IMPORTS))
    gone_direct = sorted(set(KNOWN_QT_FRONTEND_IMPORTS) - set(direct))
    for module in new_direct:
        print(f"NEW IMPORT {module} imports {direct[module]}: Qt takes shared behaviour from its neutral owner")
    for module in gone_direct:
        print(f"GONE       {module} no longer imports a Textual module: delete its KNOWN_QT_FRONTEND_IMPORTS line")
    print(f"toad.qt modules importing toad.widgets/screens: {len(direct)} (ratchet baseline {len(KNOWN_QT_FRONTEND_IMPORTS)})")
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
    return 1 if new or fixed or new_bare or rooted or new_loading or cleared or new_direct or gone_direct else 0


if __name__ == "__main__":
    sys.exit(main())
