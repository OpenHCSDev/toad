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
