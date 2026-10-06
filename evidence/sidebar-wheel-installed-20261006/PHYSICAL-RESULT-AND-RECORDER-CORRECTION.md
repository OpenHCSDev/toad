# Physical result and recorder correction

The one installed attempt stopped after 138.79 seconds without an outer timeout.
The read-only 42.7 MB source capture and two private saved SDK forks completed.
Left sidebar motion and transcript wheel/reversal/End markers were reached.
The next native target lookup refused: expected one visible ContextTree, got zero.
Right context motion and saved-return checks did not complete. This is not a
physical performance acceptance; review of the completed motion remains pending.

The actual context-before frame shows the right sidebar **open**, with Thread
and Comms panels filling the small terminal viewport. The initial explanation
that it was closed was wrong. An append-only interpretation correction preserves
that mistake without rewriting the original whole return.

ContextSessionPanel is the last declared panel. SidebarViewport (VerticalScroll)
owns the enclosing scroll and native clipping. ContextTreeTarget correctly
requires a visible tree; it must not select a hidden tree or bypass that check.
SidebarWheelJourney now performs an actual wheel gesture on the right
SidebarViewport before acquiring the ContextTree target. Existing tree wheels,
hide/reopen, tab return, draft and Undo checks remain unchanged. No backend,
renderer, timer, bound, wheel or frozen operand record changes.

Only SidebarWheelJourney differs in the recorder module's before/after AST.
Compilation without imports and git diff check pass. No test, build or App was
repeated for this correction. A raw pickle analysis initially refused to import
agent_comms in host Python; analysis used the already exported native metadata
and saved frame instead. No installed-prefix import followed that refusal.

The original three-package restoration completed once. Bohr independently closed
the existing purpose after verifying the original floor, raw return, recorded
process absence and clear private census. Raw files and both journals are held.
The source correction needs fresh affected qualification; it does not authorize
another use of the closed purpose or prove that six wheels expose the tree.

## Retained evidence

- Whole return: `.artifacts/ui-physical-publication-20261006/485-installed-purpose/whole-handback.json`
- Corrected interpretation: same root, `physical-failure-interpretation-correction.json`
- Native frame: `/home/ts/.cache/agent-scratch/puip01/evidence/capture/phase-context-before.png`
- Independent return: `/home/ts/.cache/agent-scratch/disk-cleanup-owner-20261002/485-Parent-current-ui-physical-saved-history-independent-final-floor-readback.json`

FINAL-PHYSICAL-OPERANDS.json remains the byte-exact record for the first attempt.
It does not bind this changed recorder for a future attempt.
