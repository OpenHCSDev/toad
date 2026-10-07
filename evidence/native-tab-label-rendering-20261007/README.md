# Native tab label rendering

`SessionsTabs.render_session_label` already formatted titles, unread badges and
activity frames during composition. `TabRosterWork` independently repeated the
same decisions, then hashed, encoded, retained and decoded these small labels
through preparation workers for updates. Remove that second implementation and
its `PreparedTab` projection. Composition, updates and animation now use the
original widget method.

The existing synchronization lock still serializes mounted tabs. Reconciliation
now re-reads the canonical roster after actual mount/removal awaits, completing
changes arriving during mounting before activation returns. Existing labels are
updated in place; order, close controls, underline and width invalidation remain.
Sidebar thread-row workers and transcript preparation are unchanged.

## Verification and limits

- NRA's original parser covered 288 source, 406 test and 40 tool modules before
  and after, without omissions. No replaced declaration or consumer remains.
- Existing real mounted-bar control passed, including a title publication while
  actual native mounting was suspended. Five changed modules compiled.
- Packaged saved-thread open/close/reopen passed all six existing checks, with
  original source unchanged, runtime unchanged and owned cleanup complete.
  No submitted input or provider request.
- Baseline tab reconciliation: 292 ms on open, 251 ms on reopen. Changed: 19 ms
  on open; single-digit milliseconds on reopen. These are asynchronous elapsed
  spans, not CPU attribution or exact input-to-pixel measurements.
- Overall screen switching remains roughly 450–470 ms and ACP initialization
  about two seconds. Removing this duplicated preparation does not establish
  that whole agent opening is fixed.

Original artifacts:

- `/home/ts/.cache/agent-scratch/agent-tab-preparation-timing-installed-20261007`
- `/home/ts/.cache/agent-scratch/native-tab-label-candidate-installed-20261007`
- `/home/ts/wt/comms-cleanup-live-integration-20260929/.artifacts/sidebar-live-candidate-20261006/native-tab-label-wheel`

The initial offline dependency resolver refusal preceded installation; install
used the existing complete 69-package pin list with `--no-deps`. An initial
recorder invocation named the prefix instead of its `bin` directory and was
refused before output creation or launch. Both were corrected without repeating
an application attempt. Publication and actual-default verification follow the
existing frontend owner; backend owners are preserved.

## Delivered result

PR514 merged and the existing frontend publisher switched the default `toad`
entrypoint to `runtime-native-tab-label`. The actual default `toad-comms`
open/close/reopen journey passed all six checks with unchanged original source,
unchanged runtime and no cleanup errors or owned processes left behind.
Tab reconciliation measured 13.8 ms on opening and 9 ms on reopening. Screen
switching still measured 411/419 ms; ACP initialization 2.50/2.16 seconds. This
run confirms the tab-update improvement but does not establish fast whole-agent
opening. Existing windows and backend processes were not restarted.

Actual-default receipt and original stage timings:
`/home/ts/.cache/agent-scratch/native-tab-label-default-live-20261007`.
The new prefix's complete 69-distribution RECORD readback has 2,787 matching
hashed entries. Default publication and preserved dependency metadata are in the
wheel artifact directory above.
