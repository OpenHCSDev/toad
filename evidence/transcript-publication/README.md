# PR141 implementation and urgent reconnect fix

Persistent own checkout ~/wt/toad-transcript-publication-sol-20260928.
Base ready140f4ec98b, current merged main140436514d included by mergea9fb452.
Original owned work354fba3/fbc20a4 preserved. Urgent production a2bb0e5/a5073b2
is pushed. No live installation, shared checkout/history writes or core edits.

TranscriptPresentation owns generation, dirty/checkpoint state, painted frontier
and exclusive worker. TranscriptPublication ABC cases capture actual source,
Window/Contents and generation; SnapshotPublication and CheckpointPublication own
complete transactions. Existing CheckpointPlan, CommitEvidence and mounted
HistoryWindow.histories remain authorities, not new stores/flags/engines.

Deleted root generation/dirty/checkpoint/cursor fields and read/record/compact
methods. Dispatch, source replacement, input/turn invalidation, viewport retry,
covered-history, FollowTailCheckpoint and retained pilot callers migrated.
Source replacement cancels old publication and resets frontier; final close
cancels/awaits owned checkpoint. App caller closure remains assigned to Tesla:
through=conversation.transcript.displayed_cursor. No alias or App edits here.

Urgent reconnect: ACP consumer no longer suppresses every reconnect snapshot.
Presentation derives retained coverage from existing mounted read owners and its
painted cursor. Covered same-source load is ignored; newer source goes through
existing checkpoint policy. Fresh view mounts normally. AgentReady now makes
fresh reconnected views ready; only first-connection telemetry/flash is omitted.

## Evidence boundaries

Own noneditable installed wheel of urgent production a5073b2 (same production
tree tested before the evidence commit), actual core03b6f9f and Textualc974.

- installed-family.txt: mounted UI/new publication case inherits generation and
  retirement fencing and actually paints cropped text. PASS. Controlled case,
  not native backend evidence.
- installed-retained-paint.txt: actual captured NRA26-event ACP snapshot replay
  mounts production read source and paints10 saved words. PASS.
- installed-reconnect-paint.txt: same actual captured payload through actual
  CommsUpdateConsumer with existing _reconnecting=True. Fresh view readytrue;
  duplicate snapshot with painted cursor deliberatelyunset still retains one
  read source through its actual coverage; cropped source words10. PASS.
  Captured ACP/UI proof, not a fresh native reconnect/backend proof.
- failed-native-busy.txt: actual physical Pi/ACP/loopback HTTP run reached first
  provider request, then timed out20s waiting busy sidebar before checkpoint.
  Failed attempt preserved. Native checkpoint/reconnect acceptance not claimed.
- ratchet.txt: final sourcea5073b2 versus main140436514d, zero positive deltas.

Parent owns urgent combined129+140/core303 actual shipping reproduction,
integration/pins/deployment. Next gate: consume direct App cursor caller and
parent actual fresh-view stop/start/switch/reconnect paint case. No CI wait or
unchanged test matrices. Do not call full141 ready before these gates close.
