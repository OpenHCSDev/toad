# Scoped retired worktree/runtime cleanup — 2026-09-30

Existing PR231 post-merge evidence and parent432 cleanup row; no new code feature.

Removed six merged clean worktrees with `git worktree remove` (no force), plus
thirteen obsolete runtime prefixes. Exact named paths, original heads and outcomes
are in `cleanup-receipt.json`. Branches remain and were verified after removal.
Production source changes: **0**. No package/default/owner/registry mutation.

Preflight counted **651,653,120 allocated bytes** (621.46 MiB) exclusively released
by removing the selected names, accounting for hardlinks. Home free space observed
increased from 21,535,637,504 to 22,189,920,256 bytes; concurrent process activity
means this filesystem delta is not attributed exclusively to this cleanup.

Checked clean/merged source, all ignored files (only compiled/lint/test caches on
removed worktrees), current open PR branches, canonical registry references,
current source/tool references, all worktree/runtime `.pth` dependency donors,
launcher symlinks, process command/cwd/executable/open descriptors/mappings and
process environments. The first final check refused deletion because eight live
process environments referenced `runtime-context-budget-20260929`. No deletion
preceded that refusal; the prefix was protected and the corrected custody gate
passed. Both receipts are preserved.

Retained current C3/default stage, newly assigned owner-CLI-config staging path,
standalone nativee36 and prior native packages, historical Core000/firstUI,
context-budget, canonical-native-checkpoint and ordered-view-disposal dependency
donors, TC2 `.venv` shared `pytest_asyncio` donor, original-capture driver/source
worktrees, all native journals/UNKNOWN/wire/goals/private roots/release preimages,
raw failed captures and unreviewed source.

Several further GiB were not verified disposable in the authorized scope:
`recovered-skill-validation-20260930` (1,801,129,984 bytes, OpenHCS packaging outside
this worker's ownership), `toad-restored-inbound-chronology-20260929/real-fixtures`
(912,236,544 bytes, retained native fixture/source),
`toad-workspace-growing-end-continuity-20260930/.artifacts` (498,896,896 bytes,
retained physical proof), and own compaction progress `real-fixtures`/native stack
(285,417,472 / 203,145,216 bytes, retained original/native custody). Sizes describe
allocated directory accounting, not exclusive reclaimable space. They remain.

Original raw inventory/procedure receipts remain in owned persistent
`.artifacts/resource-cleanup-20260930`. No home-wide recursive scan, worker launch,
provider call, UI rerun or repeat of parent's prior 4.88 GiB cleanup was performed.
