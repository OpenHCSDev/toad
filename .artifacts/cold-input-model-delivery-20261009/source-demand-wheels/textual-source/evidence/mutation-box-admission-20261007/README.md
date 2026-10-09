# Mutation-box admission

Ordinary Widget box measurements previously called is_attached before asking
Compositor whether the widget owns a held mutation box. The original retained
channel cProfile contains about28,000 box queries, nearly all taking that check.
Its wall/cumulative profile is not a reliable attribution of total UI CPU.

The compositor already owns transient layout_geometry, filled only for the
acquired mutation roots during original arrangement and restored in finally.
mutation_box now checks membership first and attachment only for a candidate.
Widget still uses its actual screen descriptor. NoScreen permits ordinary
measurement only when is_attached is false; an attached source retains the
original NoScreen refusal. Other errors propagate. Custom attachment and screen
behavior stays dynamically dispatched; no snapshot or cached lifetime is added.

Native arrangement, style/child epochs, full and visible maps, hit geometry,
clipping, mutation exclusions and held-box margins remain unchanged. This removes
unnecessary attachment traversal from ordinary measurement; it does not reduce
required scroll placement frames or certify all source invalidations redundant.

Existing Package parsed250 production modules with zero omissions; mutation_box
has exactly one consumer in Widget._get_box_model. New ordinary/detached sizing
plus affected held-root geometry/callback publication controls:2PASS/.49s.
Final attached/custom NoScreen refusal control:1PASS/.36s.

One original unprofiled channel-history driver run retained installed Toad ef421
and Core d4b9, replacing only native source at e7b105fd4. Native includes ffcb82
and PreparedTextArea97. Original readonly runtime:
/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/channel-history-delivery-20261007/runtime
Driver history_check.py from the same artifact; HISTORY_PROFILE=0 and new owned
output /home/ts/.cache/agent-scratch/native98-channel-history-20261007.

160 authored initial private messages,20 incoming private messages,30 PageUp;
no provider, public input, package or installed pin change. Terminal0, empty
stderr,120 mounted rows/oldest sequence33, no App exception. p95 loop28.59ms,
maximum134.26ms,38 intervals over50ms. Matching unprofiled baseline p95 28.84ms,
maximum159.89ms,46 intervals over50ms. One pair establishes no reliable overall
improvement; meaningful pauses remain. Pilot global-idle waits remain included.
Original runtime_fixture owns teardown; controller joined and no driver/output
process reference remained. Exact child birth identities were not recorded.

The subsequent final source change only restores the original attached NoScreen
refusal, exercised separately above. The normal mounted App path is unchanged;
no repeat App run was needed. Source-only/author-App evidence, not installed
physical acceptance. Parent owns durable delivery and affected live observation.
