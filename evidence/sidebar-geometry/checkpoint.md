# Mounted sidebar geometry checkpoint

Source commit: `94679c09` (two production files, 7 additions / 5 deletions).

`WorkspaceChrome.sidebar_geometry` resolves the applying mounted sidebar along
with its native peers. The ancestor visibility test now uses the same Widget
boundary as `SideBar._apply_layout`; applying `thread-sidebar` is part of that
single layout calculation even during mount/navigation membership transitions.
There is no second geometry projection or missing-member fallback.

## Actual installed acceptance

Exit 0, 2026-09-29: `tests/thread_spawn_bind_owner_installed_pilot.py`, with
`PYTHONPATH=tests`, an isolated wheel installation, the existing real Textual
application, ACP processes, native Pi, and a loopback controlled provider.
Physical fork creation, immediate child opening before its first answer, first
native response, right-sidebar Parent click, and channel-bar child click passed.
Three provider responses; no replay; no application exception.

Wheel SHA256:
`27790471903f095262991461c144b937d210ebd9abc661e44e3311cf4774d066`.
The wheel was built from an archive of exactly `94679c09`, excluding subsequent
uncommitted performance implementation. Paired Core `c1d2849b90023acf5206c35b7da4664407d6dce5`,
Textual `412b5a2b5da8875dc2f3dc5be2365abddce0537b`, native package `776dc36857e630da`.
The copied runtime's activation manifest records its original baseline Toad pin;
the wheel above replaced only Toad in that owned disposable runtime.

The fixture's in-process Comms now explicitly pins its declared private root,
root ID and package through `owners.pin_private_nk_launch`, matching current Core.
The earlier unpinned run was rejected before owner launch/input submission.
Fresh private state was used for both successful source and installed runs.
Only test-owned private processes were stopped during normal teardown. Live
owners and global packages were untouched.

Receipts: `installed-parent-child-channel.log`, `paired-runtime.json`.
Scratch owner: PR202; `.artifacts/sidebar-geometry-*` under this persistent
worktree holds packaging and disposable private-run output, not saved user state.

This is a navigation fix checkpoint. It does not establish warm first-paint
performance or full channel activity-row acceptance. CI is deferred.
