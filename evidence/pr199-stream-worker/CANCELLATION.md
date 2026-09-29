# Delivery workflow follow-up to merged #199

Paired Core #411 merged: https://github.com/OpenHCSDev/agent-comms/pull/411,
`ae68bc93e701cf3dd35b194260b2cb8cc6d1cb33` (reviewed head `193ebbf4bd6de2b0668fd25e6812163483616475`).

Actual noneditable wheel / native776 / ACP / Toad / loopback-provider journey passed cancellation before native send (zero provider requests), while provider pending, and after partial reply paint. ACP model and thinking controls work after each cancellation, and a distinct final message completes. Canceled inputs remain recorded, no replay. Typed cancellation notes paint Not sent or Native input started based on existing input owners; unknown remains unconfirmed.

Actual ACP attachment refusal (saved-owner/project mismatch, zero prompt/provider calls) paints Not sent instead of Unconfirmed. Parent separately owns actual route/startup failure investigation and global installation.

Existing published backend failure facts are decoded from the paired Core request receipt, so the request response can recover its draft without adding a contradictory second failure card. Unreported/external failures remain visible. Focused real-native cleanup IO-fault test passes; the real user's old owner log supplied the retained TimeoutError witness. Full original timing is not reproduced by that injected fault.

The final OS-denied native cwd journey passed: exactly one Not sent failure card, original fixture draft recovered, zero provider requests for that input, then a distinct new message succeeds after restoring the fixture directory permissions. The same journey with the old installed UI fails with the contradictory Not sent and Internal error / Unconfirmed pair. The old failure handler is identical in baseline #198 and merged #199; the #205 receipt consumer fixes this path.

Preserved final evidence:

- `cancel-final/cancel-stages.json` and `acceptance-complete.txt`: all three cancellation stages, painted dispositions, controls, distinct successful message; exit 0.
- `startup-not-sent/startup-not-sent.txt` and `acceptance-complete.txt`: attachment refusal; exit 0.
- `backend-failure-final/single-failure.txt` and `acceptance-complete.txt`: single typed error, draft recovery, distinct successful message; exit 0.
- `backend-old-ui/acceptance-failure.txt`: old UI demonstrably fails the same single-error assertion; exit 1.
- Core `evidence/post-cancel/`: old cached cleanup failure fails; candidate two native custody checks pass; 12 ACP contracts pass. Per-file and per-function StringDispatch/TypeSwitch counts and arm growth have no increases across the 15 changed production files. Existing external-taxonomy switches remain unchanged.

Exact completed commands are in [FINAL.md](FINAL.md). The tests ran through noneditable installed wheels, real native776, ACP, Textual UI and a localhost provider. Global #205 activation remains with the parent, paired with #412. No original user request was replayed. Own disposable stages and wheel scratch are tracked in OWNERSHIP.txt; parent `.venv` and other owners are untouched.
