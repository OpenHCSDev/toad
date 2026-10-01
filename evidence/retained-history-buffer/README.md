# Retained history buffer continuation

Integration owner: Heisenberg, PR254. Contributor: Kepler.
Base: PR254 `9e62b16dd1b4c1f37ee51876e038b1ee8c7dfbd6`.

## Scope

Trace configured viewport runway and measured directional demand through native
viewport admission, transcript paging, existing background body preparation and
physical terminal publication. Assess the actual retained 41MB source with the
existing SourceCapture, isolated st/Xvfb and same-run CPU profile. No provider
input, public owner restart or source mutation is authorized by this fixture.

Production writes require direct agreement with Heisenberg on
DirectionalPreparation and DocumentViewport methods. Transcript publication,
live/saved handoff and the active PR252 bus failure remain his scope.

## Required relation

Native viewport position and the existing PreparationDemand own scroll intent.
PresentationBudget owns bounded resource admission; PreparationRuntime and the
existing renderer own prepared resources. Views derive their runway from these
owners. No second cursor, cache, velocity tracker or resource registry.

Relevant patterns: IDEN-5 (split ownership), IMPL-13 (duplicated mechanism),
TIME-7 (copied policy defaults). Extend the original declarations and delete
replaced decisions in place.

## Acceptance

Actual saved-source startup; held PageUp, repeated/held PageDown against a lazily
growing bottom, reverse PageUp, End destination and 15-second stationary view.
Retain original physical frames, native source/viewport DTOs and same-run kernel
CPU/profile clocks. Report prepared runway, direction/idle behavior and resource
limits. Source evidence does not establish installed/default readiness, complete
lazy-history coverage or a final 50ms performance target.

Preserve original failures. A useful visible buffered-progress checkpoint may
ship through PR254 before the full performance target.

## Working source checkpoint

Production `7bdc6ec8`: **8 deleted /25 added lines**, two files.

- `widgets/presentation_window.py`: page admission previously added viewport
  **rows** to a **fragment count**. With a32-row viewport the stationary96-row
  runway and fast128-row prediction both selected the24-fragment maximum.
  Admission now divides by original measured visible body extent. The
  PreparationDemand family owns resource ordering; MovingPreparation admits the
  incoming direction before the reverse reserve. Stationary/destination retain
  the original nearest two-sided order.
- `widgets/viewport_body.py`: one derived `visible_body_rows` property queries
  native current body owners. Both page lookahead and body restoration consume
  `DirectionalPreparation.admission`; the duplicate extent/count calculation is
  deleted. No new stored geometry, cache, timer or semantic registry.

Tool closure: the existing `history_frame_publication_pilot.py` has an explicit
physical source mode. It runs actual ToadApp/LinuxDriver, the original current
Core native page reader and real TranscriptHistory against the preserved SDK
fork journal. It skips the original focused test's delayed-removal mock in this
physical mode. The existing SourceCapture retains process/runtime/root custody.
`capture_state.py` adds original native runway/demand diagnostics.

## Actual physical assessment

Read [physical-comparison.json](physical-comparison.json) for exact raw paths,
receipt hashes, resources and phase clocks. Source journal resource436 is
41,270,331 bytes, SHA256
`fc5a6209efae51c1cb82833b1e296ebeeefe9e28b180f5a02d70a2d0928084e0`.
It remained byte-identical after both completed runs. Its historical registry is
not decoded or adopted; a fresh current-format private declaration references
the protected native file. No public read, owner start, native input, provider,
SDK replay or package mutation occurred.

The selected immutable runtime was Core970bc527, installed Toad85d45b51,
Textual6b5895fa, SDK0.12.1, native593b978a. The actual UI imported this owned
source checkout. This is **source** evidence, not installed Toad85 behavior or
the full native ACP conversation workflow.

Baseline02 completed65.65s; candidate01 completed66.65s. Both used actual native
history-gutter clicks followed by held Up4s, Down4s, reverse Up4s, End and15s
idle. Both had readable saved startup and End/idle. Candidate Down/reverse/idle
PNGs and the timestamped Down contact sheet were personally inspected. All
sampled Down frames contain chat content. The video still shows discontinuous
transitions between large tool JSON and shorter messages; **reader smoothness
and transient hiccups remain open**, not fixed by this checkpoint. A4fps sheet
cannot exclude sub250ms blank frames.

The candidate's completed native states selected4–24 fragments depending on
measured density, instead of always24. After Down it retained103 rows before
and100 after a96-row baseline,203 widgets within320 and151,926 source bytes
within64MiB. At Up the93-row before reserve was below96; item/native cost and
source-edge availability still bound the reserve. Do not claim universal3x
runway or speed-proportional full physical acceptance from these stationary
marker snapshots. Moving resource ordering was exercised by the native held
keys, but demand is stationary by each completed marker.

| Phase | Baseline UI CPU | Candidate UI CPU |
|---|---:|---:|
| Up |80.2%|78.6%|
| Down |79.2%|79.6%|
| Reverse |81.5%|83.1%|
| End |46.4%|44.2%|
| Idle |5.8%|5.7%|

These are original kernel CPU deltas over video action intervals, including
native snapshot overhead. The actual loaded ranges differ (Down3 vs4 source
pages), so they are not an isolated effect estimate. **No CPU improvement or
final latency target is claimed.** Actual GIL samples674/734, zero sampling
errors. Chrome stack transitions identify code activity; they are not samples,
durations or CPU time. Heisenberg received the physical/profile paths and the
remaining reader/CPU gap directly.

Candidate offline artifacts: `capture/down-buffer-review-frames.png` and
`capture/down-buffer-review-slow.mp4`; original `terminal.mp4`, `cpu-profile.json`,
`profile-review.json` and all native phase DTOs remain beside them. Offline
encoding followed UI retirement. Both capture cleanup and offline cleanup
report no owned PID or error.

## Preserved negative and next owner

Baseline01 failed before UI launch because the caller invented a private root
ID rather than using `initialize_private_initial_protocol()`'s returned ID.
Its original receipt/log and a read-only canonical-marker probe are preserved.
Baseline02 and candidate use the initializer's return; no guard bypass or
timeout increase. Owned scratch totals approximately79MiB and is retained for
parent/Heisenberg review; the protected41MB journal belongs to the236 fixture
and is not removed by this contribution.

Heisenberg owns normal integration into PR254 and reader/publication crossings.
Parent owns packaging/activation. Remaining installed/current ACP acceptance,
fast demand observations, lazy-growing-end guarantees and global CPU closure
stay open. This source correction can be reviewed independently of urgent252
bus input/duplicate-publication work.
