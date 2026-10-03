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
