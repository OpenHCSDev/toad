"""Check the app folder the build packages, seeing only what the APK ships: the assembled
APP folder plus the recipe-built packages from SITE_PACKAGES.

    python tools/android/bundle_check.py APP SITE_PACKAGES

Run it after assemble.py. It checks the APK's start, toad.qt.android, two ways:

- it must import, run by an interpreter without site-packages; a failure exits non-zero;
- it lists every import inside a function of a module that import loaded which can reach a
  package the APK does not ship, once per line, with one import chain to that package.
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
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

from recipe_built import import_names

ENTRY = "toad.qt.android"
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

    def unshipped_from(self, site: ImportSite, loaded: set[str]) -> list[ImportSite] | None:
        """One chain from ``site`` to an import of an unshipped package that running ``site``
        runs: module-level imports of the modules it loads that the start had not; None when
        there is none."""
        came_from: dict[str, list[ImportSite]] = {}
        queue = deque([[site]])
        while queue:
            chain = queue.popleft()
            last = chain[-1]
            if not self.ships(last.imported):
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

    def lazy_unshipped(self, loaded: set[str]) -> list[list[ImportSite]]:
        """Each function-local import in a loaded module that reaches an unshipped package."""
        found: dict[tuple[str, int], list[ImportSite]] = {}
        for module in sorted(loaded):
            for site in self.sites(module):
                if (site.lazy and (site.importer, site.line) not in found
                        and (chain := self.unshipped_from(site, loaded)) is not None):
                    found[site.importer, site.line] = chain
        return list(found.values())


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
    lazy = ShippedTree([app, Path(recipes)]).lazy_unshipped(set(json.loads(modules)))
for chain in lazy:
    print(f"lazy import of an unshipped package: {chain[0]}"
          + (f"\n    reaches {chain[-1]} via {' -> '.join(step.importer for step in chain[1:])}" if len(chain) > 1 else ""))
packages = Counter(chain[-1].top for chain in lazy)
print(f"{len(lazy)} function-local imports reach a package the APK does not ship:",
      ", ".join(f"{name} {count}" for name, count in packages.most_common()))
# Fail loud, not warn-and-ship. A lazy import that reaches an unshipped package
# is a runtime `ModuleNotFoundError` waiting to fire the moment that code path
# runs. Shipping anyway hides it until a user taps the wrong row, at which point
# every symptom looks like a new bug. Expected lazy-unshipped imports belong in
# a per-package allowlist, which a maintainer updates deliberately.
# Each of these is a ticking time bomb: a function-local import that reaches an
# unshipped package. If the function fires on Qt-for-Android, the APK crashes
# with `ModuleNotFoundError`. They're allowlisted only because they haven't
# fired YET in practice. Remove a name here when the lazy import is either made
# defensive (pattern: `try: import X; except ModuleNotFoundError: ...`) or the
# function is unreachable from the Qt frontend. Adding a new name requires a
# rationale.
ALLOWED_UNSHIPPED: set[str] = {
    "zmqruntime",      # zmq surface — Textual command-palette path, not Qt-reached today
    "httpx",           # HTTP client — Textual notification/preview path
    "notifypy",        # desktop notifications — Textual only
    "dill",            # pickle extension — repl/debug helpers
    "textual_dev",     # Textual dev tooling
    "jeepney",         # DBus — Textual notification backend
    "pathspec",        # gitignore parsing — Textual file browser
    "magicgui",        # Textual form editor fallback
    "format_currency", # Textual locale formatting
    "setproctitle",    # process-title decoration
}
unexpected = {chain[-1].top for chain in lazy} - ALLOWED_UNSHIPPED
if unexpected:
    print(f"error: {len(unexpected)} unexpected unshipped package(s) reached by lazy imports: {', '.join(sorted(unexpected))}",
          file=sys.stderr)
    sys.exit(1)
