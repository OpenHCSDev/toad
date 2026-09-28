# Historical UI acceptance: harness correction

## Conclusion

Final current installed runtime acceptance: **exit 0 in 38.263 seconds**.
Toad85 with core167/169; #comms 20 historical rows, #nra 8 historical rows,
agent-comms-ux saved transcript mounted, 111 identities, live sequence unchanged.

No HistoricalSessions product change is justified by the reproduced failures.
The unguarded executable harness re-entered through Python 3.14 multiprocessing
when PreparedMarkdown started its process pool. All three relevant entrypoints
now guard `asyncio.run(main())` with `if __name__ == "__main__"`.

The asyncio.sleep predicate variant had a separate initialization race: merely
finding Select in the DOM did not establish completion of its mount. It wrote
value 36 before SelectCurrent existed, so Textual `_watch_value` emitted no
Changed message; mounting later assigned the same value and emitted no change.
Captured failure: value 36, HistoricalSessions selection generation 0, original
source label unchanged, HistoricalSessions message pump idle on Queue.get.
There was no selected-handler deadlock or blocked remove/mount in that capture.
The corrected predicate harness (not separately rerun; final acceptance uses
the original frame-aware harness) waits for a pilot frame before selection and
between channel-page scrolls. Channel history initialization likewise precedes
final layout, so polling model state alone was insufficient readiness evidence.

## Evidence and commands

The exact final installed command and process exit status are in
`installed-relationship-receipt.json`; output is in
`installed-relationship-guarded.txt`. PYTHONPATH is removed so both Toad and core
are loaded from the installed runtime, not this worktree. No provider prompt,
input replay, runtime restart, or source-data migration is performed. The normal
UI may record its ordinary painted read evidence; the bus sequence is asserted
unchanged. Screenshots remain in the parent harness output directory.

Prior observed exits:

- `actual-session-reproduction.txt`: exit 1 without main guard, child re-entry
  and BrokenProcessPool. This was not a product acceptance pass.
- `actual-session-guarded.txt`: exit 0, same real saved-session selection mounted.
- `parent-original-guarded.txt`: exit 0, full original harness against owned
  Toad84 source and installed goal-cleanup core.
- `installed-original-guarded.txt`: exit 0, full original harness using only
  installed goal-cleanup packages.
- `parent-observed-guarded.txt`: exit 1, channel scroll readiness timeout.
- `selection-task-diagnostic.txt`: retained relevant state and task-stack excerpt
  from the predicate variant, exit 1 before the added frame-readiness waits.

The passing full harness asserts historical messages in #comms/#nra, opens
HistoricalSessions via the normal screen action, changes the selected identity,
mounts a transcript page, records all 111 identities, checks app._exception is
None, completes app shutdown, and asserts unchanged live bus sequence.

## Delivered / boundaries

Only executable harnesses and evidence changed. Production selection code,
workers, read ownership and pagination policy are untouched. Both parent harness
files in ~/.local/state/agent-comms were corrected in place; exact copies are
included here. Parent owns deployment. Viewer-index PR167 is already integrated
by parent with PR169; its regression tests were not repeated here.

The retained real-source scripts reference this installation's preserved roots
and session file; they are local acceptance evidence rather than portable CI
fixtures. The native transcript is read through existing bounded page owners,
not copied into this tree.
