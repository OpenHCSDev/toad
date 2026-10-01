# Native prepared-body layout checkpoint

This source mechanism proof uses the actual ToadApp, mounted TranscriptHistory,
worker-prepared code fence, native Markdown/Stream layout and compositor.
There is no Agent, provider input, public-root mutation or substitute viewport.

The baseline installed187 native Stream arrangement runs 24 times for available
heights 80 through 103. The candidate runs once and returns equal placements
at all 24 heights. The original outer fragment box already reused its result;
this change does not fix a demonstrated outer-box cache miss.

The shared MeasuredViewportBody now inherits Textual's existing bounded box and
arrangement resource policies. Their duplicate declarations on
TranscriptFragmentView are deleted. PreparedConversationMarkdown, including
AgentResponse and StreamingMarkdown, receives the same policy through its
existing ancestor. PreparedCodeLabel declares its actual native height contract:
its row shortcut depends on width and content; its other branch delegates to
native Label. Unknown overrides and relative CSS retain native dependency checks.
There is no new result store, cache, timer, renderer or semantic authority.

Candidate invalidation proof changes real code padding from (1,0,1,0) to
(2,0,2,0), and native placements change. Setting height to 1fr then requires four
native arrangements with different geometry across four available heights.
The failed preceding padding oracle set (1,0), which kept the original vertical
padding unchanged. Its receipt is preserved, not counted as a passing check.

The baseline arrangement receipt's manual box probe supplied width fraction 1;
its two-row box observation is a diagnostic input error, not a product bug.
The final probe supplies the actual width. Placement comparisons use native
Markdown width in both runs. Final box_calls includes seven native measurements
across the initial probe and subsequent real style changes; arrangement_calls
is only the initial 24-height sequence.

All nine existing T4 guard functions pass. Authoritative refactor-audit measures
are bounded to these three production files, per file and per function:
StringDispatch, TypeSwitch and their arms remain zero; foreign absence probes
and chain counts do not grow. This is not whole TC1/T9 closure. New body types
inherit the shared policy without a consumer-list edit; an overridden height
method must declare its own contract, or native Textual conservatively declines
reuse. Two replaced production declarations are deleted in place.

The pilot lives in tests/prepared_height_contract_pilot.py. Source receipts are
kept here; raw diagnostic logs and earlier selection/serialization failures are
protected in this worktree's .artifacts/height-contract-* directories. They are
small owned disposable test output, not runtime dependencies. The old254 stage
is an active default dependency and must not be removed.

No physical first-paint, Strip reuse, total CPU or warm-speed claim follows from
these counters. One changed, normally installed saved-history A/B/A and held
scroll/reverse/End journey remains the checkpoint's acceptance boundary. The
entire remaining performance, focus, TC1/T9 and workspace scope remains in the
receiving PR264 README.
