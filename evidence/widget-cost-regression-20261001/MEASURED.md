# Regression2 discriminator: repeated height recount not confirmed

Counter/source checkpoint `a89abcdfc0524319204440b99963a9e79c1d15fa`.
Actual ordinary `/home/ts/bin/toad-comms nra-architecture`, isolated st/Xvfb,
current default279/Core485+487+488/native17d; no package/source override.
53.322s capture, 1607 physical video frames, same-run kernel CPU and py-spy
686 samples/0 errors. Exact counts come from original native method events,
not profile transitions. The local observer counted original `Widget.walk_children`
invocations and classified their original body-cost/height callers; diagnostic
DTO and SVG traversal was excluded. No installed method replacement.

| Actual phase | seconds | retained-cost walks | height-path walks | height walks/sec |
| --- | ---: | ---: | ---: | ---: |
| Input-focused held PageUp | 6.1104 | 0 | 0 | 0 |
| History-focused held PageUp | 5.9462 | 54 | 16 | 2.6908 |
| Input-focused mid-history idle | 9.6317 | 0 | 0 | 0 |

During idle the original same16 body identities and160 native widgets remained
loaded, every original membership revision remained10, history offset82/179
was stationary, follows-tailfalse, PromptTextArea focused at both endpoints.
Total idle walks56, of which33 belong to explicit diagnostic snapshots:
23 remaining walks/9.6317s =2.38794/sec, **none through retained-cost/height**.
Counter observation overhead in that interval0.8364ms.
Kernel UI CPU3.18s/9.6232s =33.045%; this residual CPU is real and is not
explained by repeated idle height subtree recounts in this run. Chrome stack
transition groups are not counts, durations, or CPU attribution. Sampled idle
stacks include original notification/locked-store/read paths; their causal CPU
ownership is not established by this counter.

## Source explains the result

`e7dbc1c3a` originally validated body count against geometry revision.
Existing production correction `bbd4ee75e3d9cd01ec7c07c7e47b43eb3dec3fcc`
replaced that with the native propagated NodeList membership revision. The
body's original BodyMeasurement owns the count; unchanged loaded membership
reuses it. Current default contains that correction. IMPL-13/IDEN-5 would be
introduced by adding another cost owner without a confirmed failure.

**No production patch justified or made.** Heisenberg275 retains integration
and pre254 comparison; Kepler owns pass-scoped admission. This draft contributes
reusable exact instrumentation and the measured finding, not a performance fix.
The completed granted body stream can hand back without holding those workers.

## Limits and preserved failures

This is the real original saved NRA thread with active sidebar workload, not a
new synthetic/paid provider stream. The original thread itself reports Ready.
Input-focused PageUp did not move history (65/65 before/after); the subsequent
native history click and held PageUp loaded/scrolled to82/179. This existing
keyboard-routing defect belongs to Heisenberg; the counter does not infer
swallowed geometry travel. No pre254 or speed comparison is claimed.

Actual pixels still show original PromptSendUnknown, Needs attention, and
context-unavailable. No replay and no all-product Ready claim. FFmpeg finalization
return255 is retained; recorder completed, valid53.567s video, cleanup0.
Original owner1983746/start35522550 unchanged and alive before/after;
installed prefix/route hashes unchanged. New public native inputs/provider
calls/owner restarts/DISPLAY0 control0. Raw artifacts remain protected at
`/home/ts/.cache/agent-scratch/perf280-widget-cost-busy-default-20261001-01`.

Machine receipt: `actual-default-discriminator01.json` with exact phase deltas,
source pins, artifact SHA256s and original custody/cleanup. Original event stream
also retained in `widget-cost01.jsonl`; idle pixels/profile/video stay at the
receipt paths. No other worker's source or proof was edited.
