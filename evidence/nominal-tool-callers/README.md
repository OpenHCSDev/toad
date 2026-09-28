# Installed tool caller closure

The parent combined installation caught an actual startup failure: Toad main
imported TOOLS and ToolDeclaration deleted by Comms287. The prior tool owner's
menu receipt used a different Toad implementation and did not prove current main.
The live runtime was not changed during this failed candidate check.

ThreadAction now holds the actual ToolRequest declaration. Five actions refer
directly to their owning tool classes; the string lookup helper is deleted.
Availability consumes the declaration's derived name. No aliases or second
catalog are introduced. Core4510dddf and Textualc9743801 are pinned together.

Verified with installed, noneditable candidate packages:

- Actual right-click on a registered thread, select Stop, and observe the real
  selected-root registration become stopped. No invocation/widget replacement.
- Complete mounted command family pilot: ACP SDK validation, command insertion,
  local execution, target menu/slash parity, archive, stale availability, channel
  pin/activity/copy and unchanged durable history. No model prompt submitted.
- Deletion guard rejects imports of the retired tool catalog/types throughout
  Toad. Existing command-dispatch deletion checks pass.
- Frozen dependency resolution succeeds. CI deferred.

Production source:15 added /12 deleted; the three-line growth is explicit
multiline imports replacing the deleted lookup helper. The actual menu pilot
adds72 test lines; the existing deletion guard adds6/removes1. Parent owns the
paired live installation; these receipts prove the candidate, not activation.
