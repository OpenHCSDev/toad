## P17: paint Core's delivered/read totals

Owner: toad-delivery-labels. Paired Core and Toad changes; P34/P36 real UI checks remain part of this batch.

The collapsed message label chose one agent's state and hid every count. Core MessageNotification now supplies ordering and one combined label, e.g. `Acknowledged · Delivered 1/36 · Read 0/36`. Toad paints that answer; its sorting and first-agent selection are deleted.

DeliveryProgress extends the existing AssignmentProgress family. PendingDelivery declares delivered=False/read=False; ReadDelivery declares True/True for model reads and human reads, keeping those identities separate. AcknowledgedProgress declares True/False. These are ClassVar contributions, not stored flags. No positional tuple or counts() method remains. Queued does NOT prove delivery: its existing active-owner pointer can describe unrelated work. No string-state switch, table, bool flag, new store, alternate codec or cache.

The old MessageNotification.read_at_ms field is deleted. The actual ShownToModelProgress owns that time and travels through the normal FieldCodec; constructor progress is required, not defaulted. Timed label formatting has one method. Core summary counts only typed proved progress; Toad has no recipient-count algorithm.

InputDeliveryBar has a different job: pending input jobs, including direct user inputs without a wire message. It cannot truthfully report a message audience. Its existing queue caption now also comes from Core InputDelivery.summary; the two kinds of count are not merged.

Source evidence: the existing refactor-audit parser covers eight production/dependency roots:1038 modules, zero parse omissions after the move (1037 before). `.artifacts/labels/census.txt` keeps the result; the broad generated site dumps were removed after confirming no readers. This is lexical source evidence, not a complete dynamic call graph. The import cycle was assignment_states → notification_assignment → coordination_tables.assignments → assignment_states. All progress declarations now live in notification_progress; consumers import that owner, with no compatibility aliases. Existing Core check imports/assertions were migrated, not executed. Actual imports/MRO/schema construction work. Real live message reads and normal codec round-trip give `Answered · Delivered 1/1 · Read 1/1` and `Acknowledged · Delivered 1/36 · Read 0/36`; no fake data or automated tests. One inspection command had a whitespace SyntaxError and was corrected; product imports then succeeded.

P36 source already declares all five status colour methods, including StatusPending and ThreadRetired, without a default. No replacement implementation added. P34 already uses Core's archive/stop declarations through the existing menu command path; view close remains distinct from stopping an agent. Actual saved-history archive/close and retired status screenshots are still required.

Search: `rg -n 'class (DeliveryProgress|AssignmentProgress|SentProgress|QueuedProgress|ShownToModelProgress)|read_at_ms:|delivered: ClassVar|read: ClassVar' src/agent_comms/notification_progress.py` shows one declaration of each type and the sole displayed-read time field. `rg -n 'def counts|\.counts\(' src/agent_comms` has no matching progress implementation or caller. `rg -n 'UnrecordedProgress' src/agent_comms/assignment_states.py` shows its module import and one construction. `rg -n 'summary|ordered|sorted' src/toad/notification_status.py` shows Core calls, no Toad sort.

Not yet installed or visually checked. Codex owns the paired build/install; actual plain-st/isolated-display checks and labels.json follow. Preserve UNKNOWN9226 and all saved sessions; no replay.
