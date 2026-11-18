"""Check the app folder the build packages, seeing only what the APK ships: the assembled
APP folder plus the recipe-built packages from SITE_PACKAGES.

    python tools/android/bundle_check.py APP SITE_PACKAGES

Run it after assemble.py. It checks the APK's start, toad.qt.android, two ways:

- it must import, run by an interpreter without site-packages; a failure exits non-zero;
- it lists every import inside a function of a module that import loaded which can reach a
  package the APK does not ship, or Textual's UI (toad.widgets/screens/app, textual.app/
  widgets/screen/containers) that the start had not loaded, once per site, with one chain;
  each must be in KNOWN_LAZY, which only shrinks.
  Such an import runs only when its function is called, so the import check never sees
  it, and on the phone it fails then, mid-session (build23's "No module named textual"
  toast). Module-level imports of loaded modules already ran; a branch the import skipped
  (qasync's other Qt bindings) is not lazy. An import inside a `try` that catches
  ImportError is the importer's own optional dependency, and one under
  `if TYPE_CHECKING:` never runs; neither is followed.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from recipe_built import import_names

ENTRY = "toad.qt.android"
FRONTEND_UI = ("toad.widgets", "toad.screens", "toad.app", "textual.app", "textual.widgets",
               "textual.screen", "textual.containers")
OPTIONAL = {"ImportError", "ModuleNotFoundError"}


@dataclass(frozen=True)
class ImportSite:
    """One import statement's target, where it is written."""

    importer: str
    line: int
    imported: str
    lazy: bool

    @property
    def top(self) -> str:
        return self.imported.split(".")[0]

    def __str__(self) -> str:
        return f"{self.importer}:{self.line} imports {self.imported}"


class ImportCollector(ast.NodeVisitor):
    """The imports a module can run, module-relative names resolved, each marked lazy when
    it sits inside a function."""

    def __init__(self, module: str, is_package: bool) -> None:
        self.module = module
        self.package = module if is_package else module.rpartition(".")[0]
        self.depth = 0
        self.sites: list[ImportSite] = []

    def site(self, line: int, imported: str) -> None:
        self.sites.append(ImportSite(self.module, line, imported, self.depth > 0))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.site(node.lineno, alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        parts = self.package.split(".")
        base = parts[: len(parts) - node.level + 1] if node.level else []
        source = ".".join([*base, *([node.module] if node.module else [])])
        self.site(node.lineno, source)
        # `from package import name` loads package.name when name is a submodule.
        for alias in node.names:
            if alias.name != "*":
                self.site(node.lineno, f"{source}.{alias.name}")

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        guarded = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
                   or isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
        for statement in node.orelse if guarded else (*node.body, *node.orelse):
            self.visit(statement)

    def visit_Try(self, node: ast.Try) -> None:
        caught = {name.id for handler in node.handlers if handler.type is not None
                  for name in ast.walk(handler.type) if isinstance(name, ast.Name)}
        optional = bool(caught & OPTIONAL) or any(handler.type is None for handler in node.handlers)
        for statement in (*(() if optional else node.body), *node.handlers, *node.orelse, *node.finalbody):
            self.visit(statement)

    visit_TryStar = visit_Try


class ShippedTree:
    """The modules the APK ships, found by name on its import path, read without importing."""

    def __init__(self, roots: list[Path]) -> None:
        self.roots = roots
        self.tops = {path.name.split(".")[0] for root in roots for path in root.iterdir()}
        self.read: dict[str, list[ImportSite]] = {}

    def ships(self, name: str) -> bool:
        top = name.split(".")[0]
        return top in self.tops or top in sys.stdlib_module_names or top in sys.builtin_module_names

    def sites(self, name: str) -> list[ImportSite]:
        """The module's imports; none when it ships only compiled or is not shipped here."""
        if name not in self.read:
            self.read[name] = []
            for root in self.roots:
                base = root.joinpath(*name.split("."))
                for path, is_package in ((base / "__init__.py", True), (base.with_suffix(".py"), False)):
                    if path.is_file():
                        collector = ImportCollector(name, is_package)
                        collector.visit(ast.parse(path.read_bytes(), str(path)))
                        self.read[name] = collector.sites
                        break
                else:
                    continue
                break
        return self.read[name]

    def frontend_ui(self, name: str, loaded: set[str]) -> bool:
        """A module of Textual's app/widget chain or of Toad's Textual frontend, not already
        loaded by the start: Qt running it builds Textual UI it never shows, and its own
        imports reach packages the APK does not ship (the 2026-11-18 pathspec crash)."""
        return (name not in loaded and any(name == ui or name.startswith(ui + ".") for ui in FRONTEND_UI)
                and self.is_module(name))

    def is_module(self, name: str) -> bool:
        """A module file of that name ships (not a class `from module import Name` names)."""
        for root in self.roots:
            base = root.joinpath(*name.split("."))
            if (base / "__init__.py").is_file() or base.with_suffix(".py").is_file():
                return True
        return False

    def reaching(self, site: ImportSite, loaded: set[str]) -> list[ImportSite] | None:
        """One chain from ``site`` to an import of an unshipped package or of a frontend UI
        module that running ``site`` runs: module-level imports of the modules it loads that
        the start had not; None when there is none."""
        came_from: dict[str, list[ImportSite]] = {}
        queue = deque([[site]])
        while queue:
            chain = queue.popleft()
            last = chain[-1]
            if not self.ships(last.imported) or self.frontend_ui(last.imported, loaded):
                return chain
            name = last.imported
            # A parent package runs before its submodule.
            for depth in range(1, name.count(".") + 2):
                module = ".".join(name.split(".")[:depth])
                if module in loaded or module in came_from or module.split(".")[0] not in self.tops:
                    continue
                came_from[module] = chain
                queue.extend([*chain, onward] for onward in self.sites(module) if not onward.lazy)
        return None

    def lazy_findings(self, loaded: set[str]) -> dict[str, list[ImportSite]]:
        """Each function-local import in a loaded module that reaches an unshipped package or
        a frontend UI module, keyed `importer -> imported` (stable across line moves)."""
        found: dict[str, list[ImportSite]] = {}
        statements: set[tuple[str, int]] = set()
        for module in sorted(loaded):
            for site in self.sites(module):
                # One finding per import statement: `from m import Name` is sited as m first.
                if site.lazy and (site.importer, site.line) not in statements and (
                        chain := self.reaching(site, loaded)) is not None:
                    statements.add((site.importer, site.line))
                    found[f"{site.importer} -> {site.imported}"] = chain
        return found


app = Path(sys.argv[1]).resolve()
site_packages = Path(sys.argv[2])
with tempfile.TemporaryDirectory() as recipes:
    for name in import_names():
        for candidate in site_packages.glob(f"{name}*"):
            target = Path(recipes) / candidate.name
            if not target.exists():
                target.symlink_to(candidate)
    result = subprocess.run(
        [sys.executable, "-S", "-c",
         (f"import json, sys; sys.path[:0] = [{str(app)!r}, {recipes!r}]; from toad.qt.android_app import enter; enter(); import {ENTRY}; "
          "print('shipped app imports toad.qt.main'); print(json.dumps(sorted(sys.modules)))")],
        capture_output=True, text=True, timeout=120, cwd=recipes, check=False)
    if result.returncode:
        print(result.stderr.strip())
        sys.exit(result.returncode)
    verdict, modules = result.stdout.strip().splitlines()[-2:]
    print(verdict)
    lazy = ShippedTree([app, Path(recipes)]).lazy_findings(set(json.loads(modules)))


def described(chain: list[ImportSite]) -> str:
    return " -> ".join([str(chain[0]), *(step.imported for step in chain[1:])])


# Each function-local import, in a module the APK's start loads, that reaches a package the APK
# does not ship or Textual's UI, when this check became per site. Each is a crash or a Textual
# screen waiting for the Qt path that calls it (2026-11-18: a restored mailbox tab ran
# navigation_preparation.launch_screen -> toad.screens.main -> ... -> pathspec). It only shrinks:
# move the frontend decision behind its host, or make the shared caller unreachable, then delete
# the line. A NEW finding fails; a listed one that is gone fails until its line is deleted.
KNOWN_LAZY: dict[str, str] = {
    'objectstate.object_state_registry -> dill':
        'dill. Qt: no caller of ObjectStateRegistry.save_history_to_file',
    'pyqt_reactive.protocols.widget_adapters -> pyqt_reactive.forms.widget_strategies':
        "pyqt_reactive.forms.widget_strategies -> magicgui.widgets. Qt: DoubleSpinBoxAdapter is built only by pyqt_reactive's own widget strategies; toad's forms use toad.qt.forms editors",
    'pyqt_reactive.services.window_manager -> pyqt_reactive.animation':
        "pyqt_reactive.animation -> pyqt_reactive.animation.flash_mixin -> formbridge.services.window_snapshot -> zmqruntime.timeouts. Qt: toad does not use pyqt_reactive's WindowManager",
    'pyqt_reactive.services.window_navigation -> pyqt_reactive.animation':
        "pyqt_reactive.animation -> pyqt_reactive.animation.flash_mixin -> formbridge.services.window_snapshot -> zmqruntime.timeouts. Qt: toad does not use pyqt_reactive's window navigation",
    'pyqt_reactive.services.window_navigation -> pyqt_reactive.widgets.shared.clickable_help_components':
        "pyqt_reactive.widgets.shared.clickable_help_components -> pyqt_reactive.animation.flash_mixin -> formbridge.services.window_snapshot -> zmqruntime.timeouts. Qt: toad does not use pyqt_reactive's window navigation",
    'textual.app -> textual_dev.client':
        'textual_dev.client. Qt: Textual devtools, only from App.run, which Qt never calls',
    'toad.application_lifetime -> httpx':
        "httpx. Qt: the terminal app's start, usage report and CLI serve; Qt runs its own start and sends no usage report",
    'toad.application_lifetime -> setproctitle':
        "setproctitle. Qt: the terminal app's start, usage report and CLI serve; Qt runs its own start and sends no usage report",
    'toad.client.platform -> jeepney':
        "jeepney. Qt: desktop notifications come from TerminalAttention.notify, Textual's",
    'toad.client.platform -> jeepney.io.blocking':
        "jeepney.io.blocking. Qt: desktop notifications come from TerminalAttention.notify, Textual's",
    'toad.client.platform -> notifypy':
        "notifypy. Qt: desktop notifications come from TerminalAttention.notify, Textual's",
    'toad.client.platform -> notifypy.os_notifiers.linux':
        "notifypy.os_notifiers.linux. Qt: desktop notifications come from TerminalAttention.notify, Textual's",
    'toad.conversation_turn -> toad.widgets.user_input':
        "toad.widgets.user_input. Qt: REACHABLE on Qt desktop (an ACP send from QtAcpSessionView), not on Android (no ACP agent runs); Qt's ACP view also lacks post, jump_to_latest, auto_name_from_prompt and publish_core, so ACP sends never worked on Qt",
    'toad.core.events -> toad.widgets.agent_response':
        "toad.widgets.agent_response. Qt: present_failure/show_log run only from Textual Conversation's AgentFail handler",
    'toad.core.events -> toad.widgets.markdown_note':
        "toad.widgets.markdown_note. Qt: present_failure/show_log run only from Textual Conversation's AgentFail handler",
    'toad.core.events -> toad.widgets.note':
        "toad.widgets.note. Qt: present_failure/show_log run only from Textual Conversation's AgentFail handler",
    'toad.live_output -> toad.widgets.agent_response':
        "toad.widgets.agent_response. Qt: streams append only from Textual Conversation's Update handler",
    'toad.live_output -> toad.widgets.agent_thought':
        "toad.widgets.agent_thought. Qt: streams append only from Textual Conversation's Update handler",
    'toad.setting_choices -> toad.widgets.future_text':
        'toad.widgets.future_text. Qt: QuotesLoading.widget runs only from toad.screens.main',
    'toad.tool_output -> toad.widgets.tool_content':
        "toad.widgets.tool_content. Qt: ToolOutput.sync runs only from Textual's tool_call",
    'toad.version -> httpx':
        "httpx. Qt: the version check is the terminal app's start",
}
new = sorted(set(lazy) - set(KNOWN_LAZY))
gone = sorted(set(KNOWN_LAZY) - set(lazy))
for key in new:
    print(f"NEW LAZY   {described(lazy[key])}", file=sys.stderr)
for key in gone:
    print(f"GONE       {key}: delete its KNOWN_LAZY line", file=sys.stderr)
print(f"function-local imports reaching an unshipped package or Textual UI: {len(lazy)} (baseline {len(KNOWN_LAZY)})")
if new or gone:
    sys.exit(1)
