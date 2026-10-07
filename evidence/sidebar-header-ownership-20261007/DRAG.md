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
