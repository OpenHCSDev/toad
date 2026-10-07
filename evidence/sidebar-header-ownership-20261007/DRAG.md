# Captured sidebar drag

SidebarResizeHandle derives width from its original primary press and each
absolute screen position. Intermediate positions have no independent meaning
for that captured control. It now declares this through the original native
Widget.can_replace_mouse_move capability. Other receivers remain ordered.
Native a5f64c26 combines only consecutive matching raw App packets under capture;
press/release, modifiers, prevention, completion-owned and routed packets retain
their original boundaries. No timer, queue or width mirror was added.

The original HeadlessDriver/App/Toad reproduction posts 36 pointer moves from a
separate thread into the actual FIFO, with 10 tabs and 12 real retained response
bodies. Baseline finishes pointer publication at 747 ms but replays old widths
until 3517 ms. Changed native source plus this override finishes publication at
728 ms and reaches final width at 1092 ms. Layout messages: 154 to 59. Final
width, original capture release and App error checks pass. Width layout frames
still cost about 100 ms; overall responsiveness remains incomplete.

Raw script, completed display observations and profiles are under
/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007:
baseline-spawn-corrected and captured-latest-motion. These are profiled headless
App observations, not terminal pixels, installed or live acceptance. The rejected
notification-only change was removed after coalesced-layout retained the backlog.
The initial unguarded multiprocessing fixture failure is preserved separately.

AST parsed 538 Toad/native production modules with zero omissions. Four original
receiver declarations supply the capability; this is the sole Toad override.
External dynamic overrides remain outside this source trace. Native barrier
controls and matched installed/terminal delivery remain separate work.

## Installed delivery

Native101 and Toad539 merged. The actual built package reproduction reached final
width at 1058 ms (pointer publication 756 ms), 61 Layout messages, width60,
capture released and no App error. Original installed left/right drag, mirrored
slider, ANSI/RGB hover and collapse checks also passed with empty stderr.
954 assets and all 2857 RECORD entries/full69 versions matched. Backend and
frontend defaults were published through their original reviewed owners; old
running windows/processes retain their loaded code. No public input or restart.
Raw installed-captured-motion and installed-edges are alongside the source runs.

The first built tool-paint check passed initial full retention/scroll reuse but
failed after resize/reconstruction with one captured source line. Its output is
preserved in installed-tool-paint. Existing WorkerStatic readiness was published
before native layout committed its new extent. Toad540 moves that existing ready
event to the original after-refresh callback, guarded by the same request and
attachment. The unchanged installed check then passed all12 complete retained
paints, resize/reconstruction, styles, source replacement, auto-width and disposal;
scroll preparation/full-map counts were zero. Live-worker reuse was not exercised
and remains null, not a pass. Raw installed-committed-paint contains this result.

Frontend default now selects committed-worker-paint-delivery-20261007/runtime;
backend defaults select tool-paint-marker-delivery-20261007/runtime. Both retain
the matched native b4b92974 and Core0b51; the final frontend selects Toadb8b699812.
Original reviewed publication and source proofs are inside those artifact roots.
No terminal footage/overall frame-time gain or live running-window upgrade is
claimed. About100ms width frames remain a concrete performance gap.

## Width-slider delivery

The width slider now supplies the same native captured-motion capability as
the edge handle. Its original press freezes track width, origin and reversal;
the latest absolute point selects width. Intermediate drag positions have no
independent action. Keyboard changes and native press/release/modifier/wheel
boundaries retain their original ordering. No second width state or queue was
introduced. The complete declared slider family has one Changed consumer,
which updates the existing SidebarLayout owner.

Toad541 merged. The unchanged installed sidebar_drag_resize_pilot passed both
sides, mirrored slider endpoints, keyboard steps, capture release, collapse
and ANSI/RGB hover, with empty stderr. The built cohort matches all954 assets,
full69 versions and2857 RECORD rows. Frontend defaults now select
sidebar-slider-delivery-20261007/runtime, carrying the current f162 native
refusal decoder alongside b4 native pointer handling. Backend defaults remain
native-refusal-delivery-20261007/runtime; loaded windows and owners keep their
code. This is installed App verification and default publication, not terminal
frame-time acceptance or an automatic running-window upgrade.

The installed raw-Driver slider burst, with profiling disabled and625 widgets,
completed pointer publication at677ms and reached final width60 at802ms; capture
released, App errorNone and stderr empty. Active completed headless-display gaps
were around53ms. The final478ms gap was idle after width settled, not evidence
of a costly frame. Raw installed-slider-motion/result.json retains every frame
and original pointer request. It establishes a concrete remaining frame-work
target, not terminal-pixel performance or a baseline-relative slider speedup.
