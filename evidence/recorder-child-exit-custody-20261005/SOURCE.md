# Recorder child exit custody

Source base: Toad bf9373d73daa58cce6e493f927660c5da1c4432e.

## Original failure

PUBLIC459 whole capture failed: st returned 1 and reported PTY EIO. The original UI incarnation was observed, not parented by the recorder; no actual UI wait result was retained. All 18 snapshot checks and empty cleanup remain independent. UI exception, graceful quit completion and origin of EIO remain UNKNOWN. Original raw capture and offline classification are unchanged.

## Owner and complete family

Existing ProcessOwner owns gate acquisition, original ParentedProcess and lifetime. OwnedProcess owns recorder-specific registered-owner exclusion. TransferredGroup owns exact incarnation observation; it cannot invent a parent wait result. Core ChildOutcome owns exit interpretation. ControllingTerminalCommand owns PTY acquisition in an acquired child session.

The same program parent must retain its real child through wait and publish that actual result. Both ordinary st and profiled st must consume this producer; profiling retains the original py-spy ancestor identity. terminal_program must resolve the actual program relation, not assume that st's direct child is always the UI. Quit, partial-launch recovery, final cleanup and status acceptance all consume the same original program result. st nonzero still fails.

The implemented producer preserves PTY session ownership: Core Platform launches a new session. The st-launched parent must relinquish its own controlling terminal before the existing ControllingTerminalCommand acquires it for the actual UI. No runtime process API or product patch is authorized. This source relationship needs affected installed acceptance later; it is not yet qualified.

Deleted the duplicated OwnedProcess/TransferredGroup retirement loops through original child.reap polymorphism. Registered native owner exclusion and profile export remain. TransferredGroup carries the original parent resource: normal retirement asks that parent to join its child and publish, then the observed group is retired if a forced parent could not finish. Actual signal requests remain distinct from actual wait outcome; disappearance is not a successful exit.

Parent review found the profile wrapper also lost st wait custody when execing py-spy. Both modes now use ProcessOwner.start_terminal/launch_terminal: a retained terminal parent owns actual st Popen/wait while the profiler remains its ancestor. ProcessOwner.launch_program owns the actual UI Popen/wait under st. Both original publications use the same acquired process/launcher/exit/cleanup contract. Both capture modes require successful original UI and st outcomes. The old profile-only success bypass and profile-terminal program mirror were deleted.

terminal_program rejects the transient Python exec gate and PTY acquisition command using their actual acquisition argv, so an intermediate Python interpreter cannot qualify the wrong final command. The redundant profiler interpreter loop was deleted. Partial launch recovery, quit, failure cleanup, original terminal custody probe and VIDEO_REVIEW consume the new original resources. The terminal probe is migrated, unrun; its earlier receipts remain historical.

PUBLIC459 receipt/log and Heis SHUTDOWN-EVIDENCE-CLASSIFICATION were read offline. No new source explains the original EIO; no retroactive UI outcome is manufactured.

## Source coverage

Original audit Package parsed Toad production 288, tests 397, tools 41 and Core dependency production 324; zero parse omissions. Historical evidence Python consumers are included in the final census as well; the original terminal_custody_probe.py is an affected direct caller. BEFORE.json records original declarations/consumer call sites. Dynamic recorder imports are explicit consumers but arbitrary runtime resolution is not proven by AST. Catalog: IDEN-8 original process incarnation versus PID; IMPL-13 complete shared lifecycle.

## Delivery boundary

Source-only task. No display/native/provider/input/package/prefix/recording launch is authorized by this branch. Future actual plain-st and profile launch/quit/forced cleanup acceptance requires a named purpose. Preserve PUBLIC459 FAIL and UNKNOWN; do not replay it. Heis owns original workflow diagnosis; Mendel owns this tool producer/consumer family.

## Current source qualification

Source compilation only, no application/module import or execution. The changed recorder, ten direct source consumers and the original terminal custody probe are compiled at the final source checkpoint. Full original Package before/after source parse and remaining call sites are retained. No plain-st, profile, PTY/ptrace, native, installed or UI acceptance has run for this producer. Actual future qualification must cover ordinary and profiled real installed UI quit/result/cleanup plus the changed abrupt-exit and wrong-interpreter resource cases in the existing probe. Those require an explicitly issued purpose, preserving the original459 negative and public owners.
