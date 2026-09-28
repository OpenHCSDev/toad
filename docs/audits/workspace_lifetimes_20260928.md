# Workspace lifetime implementation — PR116

Implementation is in progress. This checkpoint establishes application ownership
of navigation; the persistent workspace, session-state ownership and global
presentation pool remain part of this same unfinished implementation.

## Completed component in this checkpoint

- `WorkspaceChrome` owns one header and one Channels presentation.
- Nominal `WorkspaceProjection` implementations supply slot/source/activation
  behavior. View types declare locations instead of constructing global controls.
- The previous SharedChannels owner is removed; callers use the workspace owner.
- Native, pending, history/channel and file views share header identity. Slotless
  views park it. Source binding and destination retirement checks precede transfer.
- Conversation composition and AgentReady no longer start an unused shell. Its
  existing owner starts on real shell use, including the actual first-use command.

This stage still transfers chrome between existing mode screens. It is not the
final persistent-WorkspaceScreen topology and does not claim a bounded rich UI.

## Current validation

Base: current main6662485, including watcher109/113 and pending unread112. Exact
core492e26de354df6fe020ca69b55fdcd92fb06778e; Textual16ede007 during these runs.

- Ownership/resource guards and the cross-view/shared-source pilot pass.
- Eleven focused navigation/sidebar/first-frame/ownership cases pass in48.31s;
  peak305.9MiB, zero swap, one worker.
- Strict16-tab empty probe: one strip,17labels/17close buttons,2,280registered
  widgets; first-return median40.24ms/max52.51ms. Warm medians43.03/43.62ms,
  max63.27ms. Four reflows remain. This probe preceded the lazy-shell change.
-64-tab probe with the lazy-shell change reached its240s runtime limit and did not
  produce a completed receipt. Peak330MiB, zero swap. Its phase/idle/teardown delay
  needs diagnosis; this is explicitly not passing scalability acceptance.

The native editor handoff dependency is [Textual #8](https://github.com/OpenHCSDev/textual/pull/8).
It preserves actual document and undo/redo identity across editor retirement;
307TextArea tests pass. Its integration into the session owner is still pending.

No installed runtime, live data, user preview or other agent worktree was changed.
