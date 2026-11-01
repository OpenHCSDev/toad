# Remote debugger context: functional candidate, not an installed fix

The accompanying `cpython-debugger-context.patch` belongs to CPython's
`Python/ceval_gil.c`, not Toad's renderer or its runner. It is retained here so
this runner's platform dependency, exact proposed repair and demonstrated scope
are reviewable. It is **not** an alternate launcher, import preload, retry or
permission bypass. No live Python binary/library was replaced.

## Failure and owner

On CPython3.14.8, retained physical run11 and independently read mobile06 fail
before opening the helper:

```
Can't open debugger script .../operation.py
  File "<string>", line 1, in <lambda>
KeyError: '__import__'
```

`run_remote_debugger_script` audits/opens/reads/closes source under the
interrupted frame. Only afterward does `run_remote_debugger_source` create its
fresh namespace. The default `PyFile_OpenCodeObject` imports `_io.open`;
`PyImport_Import` consults the interrupted frame's builtins. A legitimate empty
builtin mapping therefore breaks the debugger itself. The interrupted constructor
is unidentified; run14's separate timeout remains unexplained.

Exact source: v3.14.8, commit
`8e6e75d9102e39bed2a2b279203a396741180f12`. The debugger owner file is identical
on the checked compatible3.14.9/3.14.10 tags;3.14.10's file-open/import owners are
also unchanged. NRA's Python AST does not parse these C files; the C call chain
was read manually and checked against installed disassembly.

## Repair and audit difference

The original remote-debugger audit refusal remains first. The existing loader
body becomes one private C callable, invoked through a real Python frame with
interpreter-owned builtins. The original application frame stays in the normal
frame/GC chain. The embedder's open-code hook is still called; global import
behavior, source reading/closing and payload execution are not replaced.

**The complete audit trace is not equivalent.** Successful execution now emits:

1. `cpython.remote_debugger_script(path)`;
2. `compile` / `exec` for the context lambda, filename `<string>`;
3. the existing `compile` / `exec` for payload source, filename `<string>`.

The initial proposal incorrectly put context preparation ahead of the original
audit. Review caught this; the published patch restores that audit gate first.
The extra context events remain explicit. A policy refusing them prevents source
opening and reports a context-entry error. A close error still reports the error
then executes already-read source, matching the original loader body.

## Functional build and native controls

A separately owned3.14.8 build used existing GCC16.1.1/make, no new toolchain,
PGO/LTO/BOLT/JIT/tail-call chase, and at most two make/compileall jobs. Configure,
make and private altinstall completed0 in18.4s/109.6s/13.0s. Built patch SHA256:
`5a679cd8875271a4c7eace7ce088b5f93f261076b929987e1276b6161ef9857d`;
functional binary SHA256:
`e18b6c81a63f9683beca2d20c9e56225da3207b68530bae2eaa26b6bf351e4fe`.
These identify measured artifacts, not a runtime publication. Existing `BoundedRun`
owned process retirement and deadlines; no output for180s failed the stage.
This nonmatching compiler build is **not release-performance evidence**.

One native batch completed0:

- one fresh unpatched empty-builtins child reproduced the source-open failure;
- 18 patched controls: nine cases under full and empty interrupted builtins;
- normal execution; refusing request/compile/exec audit hooks; real embedder-hook
  acceptance/refusal; read/close failure; payload failure;
- executing cases retained the original frame and cyclic guard through
  `gc.collect`; every case preserved its active exception and builtin mapping;
- all19 typed target identities independently absent after retirement.

These are exercised counterexamples/controls, not a proof over every CPython state.
The guard has other strong references; this is not a sole-root liveness proof.
The fresh control target deliberately runs a busy select loop, not a production
workload. The separate actual Toad run below exercises the unchanged application.
The disposable control extension/script targets never loaded into a user app.

## Actual private Toad

The unchanged shared runner then completed one real default-launcher journey0:
saved history, held PageUp/PageDown, reversal, End, wheel scrolling and normal
retirement. It obtained31 observed callbacks,17 explicit startup-pending results
and one exec result. The screenshot shows saved message bodies and STANDARD
mode; no physical timeout or source-open failure occurred in this run.

Admission checked1013 module locations; HOME/XDG/database/palette, selected and
opened root, and saved-source identities were private. There were **zero ACP
bindings**: this does not qualify bound-ACP behavior, mobile1391 or errors1389.
The controller used the installed source owner to copy history. The target used
the functional interpreter with a byte-compared copy of5295 regular installed
package files, declaration-derived console scripts and an existing Neovim payload
verified through its archive owner. No native download or fabricated build.json.
A setup assertion initially confused Core's package root with site-packages;
that failure is retained, and only script generation was completed afterward.

st/Xvfb/encoder retired0, all four frontend/resource identities were independently
absent, and the copied root was stopped. Original sessions, input dispositions,
phone/editor processes, desktop/pointer and scientific data were untouched.
The separately approved metadata/profile capture remains unused.

## Receipts and remaining work

Owned retained evidence under `/home/ts/.cache/agent-scratch/pi-ui-performance/`:

- `cpython-functional-build.log`, `cpython-functional-startup.log`;
- `cpython-native-controls.log`, `cpython-native-control-absence.log`;
- `cpython-functional-toad-{prepare,finish}.log` and native-payload log;
- `cpython-functional-toad-01/{admitted.json,frontend/end-return.png}`,
  typed retirement/copy-stop records and `cpython-functional-toad-absence.log`.

Native case inputs/results and the functional source/prefix are retained under
the allocated Core checkout's `platform-source/` pending review. One-shot build
code was retired after its successful result. Input hashes are observations,
not a new runtime stamp. Integration still needs a qualified interpreter/build
selection: `RuntimeStack.build` currently keys reuse by Core commit and lock
hash only. The runner's repository-identity work must use the existing
`RecordedBuildIdentity`/`RuntimeResolution`/`RuntimePackage` owners; a mutable
prefix/module location is not a repository commit. Installed acceptance and
measured production source-lifetime/performance repair remain open.
