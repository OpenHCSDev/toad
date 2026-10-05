# Recorder child exit custody

Source base: Toad bf9373d73daa58cce6e493f927660c5da1c4432e.

## Original failure

PUBLIC459 whole capture failed: st returned 1 and reported PTY EIO. The original UI incarnation was observed, not parented by the recorder; no actual UI wait result was retained. All 18 snapshot checks and empty cleanup remain independent. UI exception, graceful quit completion and origin of EIO remain UNKNOWN. Original raw capture and offline classification are unchanged.

## Owner and complete family

Existing ProcessOwner owns gate acquisition, original ParentedProcess and lifetime. OwnedProcess owns recorder-specific registered-owner exclusion. TransferredGroup owns exact incarnation observation; it cannot invent a parent wait result. Core ChildOutcome owns exit interpretation. ControllingTerminalCommand owns PTY acquisition in an acquired child session.

The same program parent must retain its real child through wait and publish that actual result. Both ordinary st and profiled st must consume this producer; profiling retains the original py-spy ancestor identity. terminal_program must resolve the actual program relation, not assume that st's direct child is always the UI. Quit, partial-launch recovery, final cleanup and status acceptance all consume the same original program result. st nonzero still fails.

The implementation must preserve PTY session ownership: Core Platform launches a new session. The st-launched parent must relinquish its own controlling terminal before the existing ControllingTerminalCommand acquires it for the actual UI. No runtime process API or product patch is authorized. This source relationship needs affected installed acceptance later; it is not yet qualified.

Delete duplicated OwnedProcess/TransferredGroup retirement algorithms through original child.reap polymorphism, while retaining registered native owner exclusion and profile export. Retain actual signal requests separately from actual wait outcome; an observed disappearance is not a successful exit.

## Source coverage

Original audit Package parsed Toad production 288, tests 397, tools 41 and Core dependency production 324; zero parse omissions. BEFORE.json records original declarations/consumer call sites. Dynamic recorder imports are explicit consumers but arbitrary runtime resolution is not proven by AST. Catalog: IDEN-8 original process incarnation versus PID; IMPL-13 complete shared lifecycle.

## Delivery boundary

Source-only task. No display/native/provider/input/package/prefix/recording launch is authorized by this branch. Future actual plain-st and profile launch/quit/forced cleanup acceptance requires a named purpose. Preserve PUBLIC459 FAIL and UNKNOWN; do not replay it. Heis owns original workflow diagnosis; Mendel owns this tool producer/consumer family.
