# F0: automatic Textual debt ratchet

Use the existing packaged `agent-comms-ratchet` on `src/textual` for every
pull request targeting `main`. Any measured increase fails the job.

The measurement owner is `agent_comms.debt_ratchet.Measure` and its existing
families; the source boundary and nonzero failure policy belong to its
`compare` and `main`. This PR wires those owners into GitHub Actions. It adds
no scanner, waiver, native builder, or full native test suite.

Pin the checker to Core `d41601c16d74e9e3e4195b6527fb218b8fe14af9`,
the exact `[tool.uv.sources].agent-comms.rev` in Toad main at dispatch.
Read-only token permissions, full history, original PR base/head revisions,
and no production-path filter keep the stable **Debt ratchet** status present
for every main PR. Parse failures and checker failures remain failures.

Implementation first; validate the complete workflow afterward through its
actual pull-request job. Tristan owns required-check settings and administrator
bypass policy. This PR makes the check automatic; it does not change settings.

Native performance branches 52 and 53, their source, and retained wheels stay
published and unchanged. Their joined installed sidebar journey remains open.

## Qualification

Actual automatic pull-request run [37175953862](https://github.com/OpenHCSDev/textual/actions/runs/37175953862)
passed at workflow source `1170bc24a22622becb1573264ab765fac13976e3`.
The GitHub runner installed the exact pinned package and ran the original CLI.
No full native suite, source overlay, new local environment or provider run.

Final local controls reused the existing source-equal d416 installed checker.
The workflow-only comparison exited 0. The original published style cohort
branch exited 1 for +3 GodClassExcess in each of Styles and DOMNode. That
negative remains evidence, not an exception: performance53 must reduce those
increases before its eventual ratchet qualification.

Added one 34-line workflow, deleted 0 production lines. No second measurement
implementation. Full before/after reports are retained in the existing WT's
`.artifacts/f0-packaged-debt-ratchet-20261004`.
