# Shared original PTY custody

Source semantics first, existing owners and all consumers, one coherent batch,
validation last. Reuse current checkout; no new environment or native package.

The existing PtyProcess/AttachedChild already owns exact process identity, group
retirement, stdin and resize. TerminalExecution/TerminalOperation owns acquisition
task and result. Shell/ShellOperationalSource stores a raw descriptor, task,
subprocess, PID, transport and finished flag, and reimplements killpg/grace/reap.
LocalDecisionPTY independently creates/reads/kills a PTY and retains an active
flag plus descriptor/subprocess. These are IMPL-13/IDEN-8/BOUND-2 custody copies.

Extend original PtyProcess acquisition to own descriptor/reader/transport scope
and borrow launch argv/environment/cwd/geometry from original policy owners.
Migrate terminal execution, retained shell and MCP decision ALL consumers once.
Shell borrows original TerminalOperation acquisition/task instead of retaining
parallel process/PID/finished state. Remove raw openpty/spawn/signal/FD retirement
from both consumers in the same change. No second PTY class, state/store/codec,
compatibility forwarding or renderer/framework.

Interactive shell controlling terminal is genuinely distinct from package MCP
direct exec. Existing ChildCommand owns typed initialization AFTER exec. Its new
ControllingTerminalCommand member acquires the controlling TTY then execs the
original shell argv in the SAME child PID/group. AttachedChild already owns
setsid; delete Python preexec_fn instead of repeating launch orchestration.
Arendt supplies this single existing-family member in Core commit
a3a1b8f69f61acb0b01e92a0ac5a9ed161b28f9f; Toad owns all consumers.
Keep MCP exact argv, NODE_OPTIONS/NODE_PATH removal, inventory currentness,
human-only challenge, visibility revocation, bounded output and operation wait.
Do not shell-interpret MCP argv or infer approval from process outcome.

All original SurfaceBinding attach/detach, output/resource/geometry, history and
UNKNOWN remain. No Heisen viewport/style/frame or Arendt runtime source edits.
Heis grants these Toad paths; Arendt has no ChildStdio/AttachedChild claim.
Parent588 display capture and notification logging gap are separate.

Final one affected installed retained shell/App/PTY and existing package MCP
journey after complete source closure, reusing a released matched holder.
No provider, current default edit, new helper fleet or unchanged settings gate.

## Published source closure

Five production files now use one existing PtyProcess acquisition owner; it
opens the original PTY, connects its reader, registers the original AttachedChild
under AsyncExitStack and publishes that same resource only after acquisition.
Cancellation during spawn joins the same acquisition before descriptors release.
Interactive Shell borrows the original TerminalOperation task/readiness/outcome;
MCP borrows the same PtyProcess resource without acquiring shell semantics.
No raw process/PID/FD/task/finished/active copies remain in either consumer.
Three existing fixture consumers now inspect original acquired custody instead
of deleted private subprocess fields.

Current-main production delta: five files, 223 added / 369 deleted. Core's
separate contribution adds 14 lines to the existing ChildCommand family.
MCP preserves its 120-second forwarding budget and separate 2-second completion
wait, output cap, sanitized environment, exact argument vector and human-only
challenge. Its controller predicate is borrowed from the original modal; PTY
geometry is borrowed from the original TerminalState. No default geometry copy.

After source evidence parses 289 Toad modules, 391 test modules and 311 Core
modules with zero omissions. TerminalOperation has two lexical declarations:
Toad's acquired PTY operation and Core's completed compaction operation; these
are distinct existing domain facts, not competing process ownership. All other
selected owner definitions occur once. Receiver identities and dynamic dispatch
are read semantically; AST is not a dynamic-resolution proof.

The published Core contribution is now pinned directly for the paired check;
its merge is not a validation prerequisite. Final installed checks remain
pending only release of the matching existing package holder. No speed/frame/publication/provider or
full headless completion is claimed from this source checkpoint.

Package checkpoint pins Core a3a1b8f69f61acb0b01e92a0ac5a9ed161b28f9f,
Textual 0ab687e007fca311ce9f786634d8f5fc991ff808 and SDK 0.12.1.
Normal uv lock resolved 99 lockfile packages in 1.73 seconds, changing only
the three Core reference lines. Installed baseline dependencies will be derived
from the existing holder, not assumed from the lockfile total. No environment
or native copy was created.

Installed shell01 started the real original PTY and reached busy input, then
failed its immediate focus assertion. Existing Textual Widget.focus queues
App.call_later(set_focus); the old threaded os.write happened to yield first.
Corrected the original fixture to await its native callback through pilot.pause
before the unchanged focus assertion. No production change or injected focus.
Raw shell01 failure is retained; its owned children are absent.

## Actual installed checkpoint

Same released style22 holder, normal 69-package frozen recipe, authentic VCS
metadata and 928 byte-equal source assets. Native2b unchanged/full trusted.
Retained-shell App/PTY02, real native-package MCP full decision family and
registered ACP streaming-terminal13-projection journey all passed. Owned
processes absent; terminal PTY masters0→0. Three consumer journeys exercise
the one changed acquisition; no source overlays or protocol/state mocks.

Raw shell01 negative preserved; only original native-focus fixture timing was
corrected. MCP crossed its existing100s diagnostic threshold and completed
under its125s test bound; traceback retained, no latency claim. Actual shell
paint exposes the shared ChildCommand -m double-execution runpy warning.
Arendt owns the original decoder/argv closure in Core590; no stderr filter.
Pair final readiness awaits that concrete producer correction and its affected
installed shell check, not a repeat of the unchanged MCP or ACP journeys.
No physical-st/native-owner/provider/public-default/full-headless claim.

## Final ready pair

Normal-main joined Toad5124100544146ba25593ab0dc329af258039c2ab +
Core5cf5d0d880678bbcc7fc9591e6bd24397683ab91, Text40/SDK/native2b
unchanged. Existing ChildCommand owns canonical import/decode/argv once across
all3members. Core contribution20+/6deleted; Toad five production223+/369deleted.
Final affected installed ShellApp/PTY03 passed, original terminal paint has no
double-initialization warning, child/task/model/editor/tab-return/directory/
retirement assertions retained. Unchanged MCP and registeredACP checks retained
without repetition. Same69 holder;928sourceassets unchanged after App, cleanup0.

READY.json is scoped source+three affected installed consumer acceptance.
No physicalst/fullUI/nativeowner/provider/performance/fullheadless claim. Raw
shell01 failure and MCP100s diagnostic retained. Borrow released to Sch/Heis
after final metadata/source receipt; public/default/native originals untouched.
