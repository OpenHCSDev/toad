"""Source census using refactor-audit parsing; no runtime resolution claim."""
import ast
import json
from pathlib import Path
import sys
from dataclasses import replace
sys.path.insert(0, "/home/ts/code/projects/nominal-refactor-advisor/skills/refactor-audit/scripts")
from audit.findings import Package, ParsedModule
from audit.repository import Repository

wt = Path(__file__).resolve().parents[2]
symbols = {"ThreadRowsWork", "TabRosterWork", "ThreadRowsRenderTask", "TabRosterRenderTask",
           "prepare_thread_row", "prepare_thread_presentation", "prepare_tab", "RendererWork",
           "ThreadWork", "RenderTask", "ReusableRenderTask", "Renderer", "RenderProcessPool",
           "PersistentRenderClient", "ThreadRowPresentation", "PreparedThreadRow", "PreparedTab"}
owners = symbols | {"SidebarGroup", "ChannelGroup", "RelationshipRows", "SessionsTabs", "SidebarObservation", "SidebarProjection"}

def describe(package):
    records = []
    for module in package.modules:
        for node in ast.walk(module.tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in symbols:
                records.append({"kind": "declaration", "file": module.path, "line": node.lineno, "name": node.name,
                                "bases": [ast.unparse(b) for b in node.bases] if isinstance(node, ast.ClassDef) else []})
            if isinstance(node, ast.ClassDef) and node.name in owners:
                records.append({"kind": "members", "file": module.path, "line": node.lineno, "name": node.name,
                                "members": [ast.unparse(n.target) if isinstance(n, ast.AnnAssign) else n.name
                                            for n in node.body if isinstance(n, (ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef))]})
                records.append({"kind": "body", "file": module.path, "line": node.lineno, "name": node.name,
                                "source": ast.unparse(node)})
            if isinstance(node, ast.Name) and node.id in symbols:
                records.append({"kind": type(node.ctx).__name__, "file": module.path, "line": node.lineno, "name": node.id})
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in symbols:
                        records.append({"kind": "import", "file": module.path, "line": node.lineno,
                                        "name": alias.name, "module": node.module, "alias": alias.asname})
            elif isinstance(node, ast.Attribute) and node.attr in {"prepare", "render_task", "prepare_thread_rows", "_reconcile_tabs"}:
                records.append({"kind": "unresolved_dotted_candidate", "file": module.path, "line": node.lineno,
                                "name": ast.unparse(node), "context": type(node.ctx).__name__})
    return {"root": package.root, "revision": package.rev, "parsed": len(package.modules),
            "parse_omissions": list(package.unparsed), "records": records}

before = [Package.load(Repository(wt), "40af80b4", root) for root in ("src/toad", "tests")]
after = []
for package in before:
    modules = tuple(ParsedModule(m.path, (wt/m.path).read_text(), ast.parse((wt/m.path).read_text(), filename=m.path), m.name)
                    for m in package.modules)
    after.append(replace(package, rev="working source after coherent family migration", modules=modules))
dependencies = [
    Package.load(Repository(Path("/home/ts/wt/comms-cleanup-live-integration-20260929")), "ad7bf20bc5a30ee7728d4b6f22794ae1cbf49a94", "src/agent_comms"),
    Package.load(Repository(Path("/home/ts/wt/textual-intrinsic-placement-after18-20261001")), "23822923a02b75a1fad10751d97dc009c36b598b", "src/textual")]
report = {"before": [describe(p) for p in before], "after": [describe(p) for p in after],
          "dependency_boundaries": [describe(p) for p in dependencies],
          "limits": ["Tracked Python modules in entire declared roots; no syntax failure suppressed.",
                     "AST references/members and source bodies are evidence, not dynamic import/MRO resolution.",
                     "Dotted prepare/render_task candidates include unrelated owners; receiver resolution remains semantic review.",
                     "External installed C extensions, generated runtime mutations and third-party packages outside declared roots are not parsed."]}
path = Path(__file__).with_name("ast-preparation-before-after.json")
path.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"roots": [{"root": d["root"], "parsed":d["parsed"], "omitted":d["parse_omissions"]}
                           for d in report["after"] + report["dependency_boundaries"]], "report": str(path)}))
