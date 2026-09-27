# S4 mounted paint integration — 2026-09-27 America/Toronto

Owner: S4, explicitly assigned the remaining mounted validation and focused fix.
Own persistent worktree: /home/ts/wt/toad-s4-read-routing-20260927.
Branch: codex/s4-mounted-read-basis-20260927. Published-main base: 0894005.
Core dependency: https://github.com/OpenHCSDev/agent-comms/pull/137,
implementation 4aa1371, normal PR136 merge b3acdf2, partial-paint support a410de9.
No dependency pins or live runtime were changed; parent owns pin refresh/deployment.

## Behavior and ownership

CommsChatView's after/expanded_after gate depended on retired read watermarks.
The new bounded-page pilot times out against archived base source: two fully
painted rows cannot be read while older rows remain. The old all-page gate also
prevents a painted new arrival from being acknowledged in the follow/refocus path.

The widget now retains original page proofs for bounded mounted channel rows,
selects only compositor-painted message bodies, and passes those immutable
subsets to core. It keeps other mounted rows pending for subsequent scrolling,
drops evicted rows, and clears evidence when history identity changes or unmounts.
It never builds read keys or advances its own watermark. Core DisplayBasis.select
intersects with the fetched membership, and core ChannelDisplayScope validates
projection semantics independently of read progress. Participant/viewer creation
and bus identity remain server-validated. DM retains its conservative inbound
contiguous-tail gate and also restricts evidence to painted rows.

HistoryReadRequest cache identity includes bus inode and viewer creation identity.
An inode replacement with unchanged high-water now reloads channel and DM history.
New tests fail in both cases against the original source. DM uses name/created_at,
without the compatibility epoch attributes; ordinary turn claims keep identity.
No native provider, delivery, recovery or lifecycle mechanism was changed.

## Validation

Use existing /home/ts/.cache/toad-merge-pr65-314-20260927/bin/python (3.14.2).
Installed Textual is fork revision 4fa6a9c440eaaa7dfaad45a33af146fc4b7e922e.
Each pilot had a separate outer timeout 60; each source runtime was mounted with:

    PYTHONPATH=src:/home/ts/wt/comms-refactor-s4-read-routing-20260927/src:/home/ts/code/projects/metaclass-registry/src
    TMPDIR=$PWD/.artifacts/s4/tmp
    timeout 60 <python> tests/<name>_pilot.py

Passed mounted pilots:
- dm_rebind_paint: stale in-flight old-peer ACK cannot read a hidden replacement.
- channel_display_basis: two painted rows read, ten omitted rows remain unread;
  any-mode expansion of the hidden tab does not read an older DM.
- channel_partial_paint: each submitted proof contains only painted bodies;
  subsequent scrolling acknowledges the remaining captured rows.
- channel_scope_expansion: older newly included history appears without a new tail.
- channel_any_mode_ui: menu changes mode, hidden traffic stays unread.
- channel_unread_follow: async roster resize, arrivals, scroll-up and refocus.
- channel_marker_notice: pre-ledger root emits one visible warning, no false read.
- divider_unread_paint: a visible divider with offscreen body does not read it.

channel_history_reader_pilot: 4 cases pass, including both channel/DM bus
replacement subcases, turn-claim stability, mode expansion and background admission.
Ruff F checks pass for both production files and six touched test files; diff check
passes. See test-results.txt; raw failure/pass logs and archived base source remain
in .artifacts/s4. User requested artifacts be preserved after interruptions.

Two existing fixtures needed to model the current contract: channel_marker_notice
removes the newly created test ledger before reopening to simulate a legacy root;
writing a legacy marker after migration intentionally does not remigrate it.
Divider-only testing gates automatic ACK while arranging that geometry, because
initial tail paint now legitimately reads the body. Follow testing waits for the
committed layout after async participant hydration instead of assuming one tick.
No assertions were removed or weakened; the new partial pilot inspects every
submitted proof against the real committed compositor geometry.

NRA was used from /home/ts/code/projects/nominal-refactor-advisor. Its Python 3.11
environment cannot parse Toad's 3.14 type-parameter syntax; that failed scan is
retained. Re-running its actual source with existing Python 3.14 completed 79/79
detectors, none omitted, exact_compact_global. Context: full src/toad plus current
core src/agent_comms; reports limited to the two touched production files. One
remaining HistoryKind case-recovery finding is outside this focused integration;
no new overlapping refactor was undertaken. See nra-summary.json. Authored semantic
patches are validated by these tests, not claimed as automatic equivalence proofs.

This is mounted local Textual/Toad test-app evidence, not live deployment, installed
wheel validation, paid-provider or CI evidence. No installs/restarts or uncertain
Comms input replay. Parent merges both focused PRs, refreshes the coupled pins,
and decides activation. No remaining S4 mounted implementation task.

Published draft: https://github.com/OpenHCSDev/toad/pull/77. Validated source
e9a0542 (implementation b71aa26 plus publication-after-mount ordering). Remote
head verified; final checkpoint is evidence-only. Core source a410de9/PR137.
