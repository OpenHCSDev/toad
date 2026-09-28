# Preserve Channels on tab switches

## Pin-compatible base

This fix starts from Toad `8adfcad0302ae1ffd6ab5074486cf0a5cf8c24e1`, the locally
pinned version and current main at investigation time. Its dependency pins remain:

- agent-comms `f7716d542135bc8a41833561c05e2170aa166ac8`
- Textual `4fa6a9c440eaaa7dfaad45a33af146fc4b7e922e`

The installed runtime's `comms_sidebar.py` and `session_view.py` blobs matched
this base exactly. Validation overlays the candidate Toad source on those
installed dependency files; it does not substitute the separate performance
branch's older core API or newer Textual features.

## Cause and correction

`CommsSidebar._mode_changed` scheduled retirement after the destination's first
frame. Retirement removed the inactive tab's channel children and discarded its
row map and last snapshot. Returning to that tab therefore presented an empty
roster before rebuilding it from cached source data.

Tab switches now preserve the keyed channel rows and their presentation state.
Inactive spinner timers pause. Existing source observation and keyed reconciliation
still apply actual changes; closing a screen still tears down its rows normally.

Retained rows are not route authority. Navigation checks the route-file stamp
before the first frame and hides an outdated route until the ordinary canonical
validation completes. A hidden sidebar does not take the unchanged-revision fast
path, so validation can restore it even if the source revision itself is unchanged.

This deliberately retains channel widgets for open views rather than trading a
visible reload for lower inactive-widget counts. Shared presentation ownership is
a separate potential optimization; this fix does not claim constant memory for
arbitrarily many open tabs or universal low-latency navigation.

## Verification

- `channel_roster_retention_pilot` failed before with **“Warm channel rows retired
  on tab switch”** and passes after. It checks three warmed views, stable row
  identities, a non-empty native channel roster on every observed warm frame,
  real source updates, immediate hiding on route replacement, and row cleanup
  when a tab closes.
- **17 targeted pilots pass in 80.70 s**: sidebar geometry/scroll/selection,
  loading views, sorting, asynchronous activation, shared readers, spinner
  behavior, and route/ingress guards. Peak memory 433.9 MiB, zero swap.
- The first targeted run passed 15 cases and hit a disposable-directory cleanup
  race in `default_route_admission`. That test now drains its executor after UI
  teardown and before deleting the private wire. Assertions are unchanged;
  the complete targeted repeat passes.
- `many_tabs_return_pilot --empty --cycles 1 --peers 8 --channels 2` passes with
  **zero replaced thread rows** across all three passes. Warm forward/reverse
  headless switch medians are 19.49/21.52 ms, maxima 38.89/51.45 ms. First revisits
  and loop gaps remain larger; these are headless observations, not terminal
  latency guarantees. Closed-tab routes still reconcile on activation.
- Native capture `toad-roster-native-1` completes **43 actions across ten thread
  tabs and a channel view** on an owned Xvfb display. The sampled snapshots have
  **44 repeatedly observed channel keys across 11 modes, with zero observed
  identity changes**. The every-frame assertion belongs to the pilot above;
  sampled native snapshots alone cannot prove absence of every transient frame.
  Native scope peak 628.9 MiB, zero swap; owned capture children were stopped.
- Scoped Ruff and `git diff --check` pass. All runs were serial, one pytest
  worker, with 4 GiB/no-swap cgroup limits.

The native observer now hashes transcript events through the pinned core's
`TranscriptCodec`, replacing obsolete universal event-field assumptions. It also
records channel widget IDs for `analyze_channel_rosters.py`.

## Pin handoff

The user assigned comms-pin updates to another agent. This branch only publishes
the Toad fix and verification. The local stack manifest, lockfile, launcher,
installed packages and running user UI/owners were not changed.
