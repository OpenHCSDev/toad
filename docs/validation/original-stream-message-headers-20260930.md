# One header for the original streamed message

Owner: Schrodinger. PR229. **3 production lines deleted, 13 added.**

## Cause and ownership

A single native assistant answer acquired two live Agent/time headers when the
initial asynchronous snapshot published coordination context between provider
chunks. SnapshotPublication unconditionally called LiveOutput.boundary although
its original CommitEvidence retired only the previous committed history. The
uncovered active answer stayed mounted but lost its stream association, so the
next chunk created a second response. CheckpointPublication contained the same
consumer bypass.

Both publications now pass their actual original-source retirement candidates to
LiveOutput.retire_presentations. The existing serialized stream owner ends only
associations whose actual blocks are being retired. Context publication and a
checkpoint signal are not output boundaries. Existing turn/input/tool boundaries
remain owned by their declared lifecycles. No text comparison, seen registry,
header flag, Frame mirror or second stream store was added. This closes BOUND-2
(owner bypass) and IDEN-5 (source signal confused with resource retirement), using
the existing CommitClaim family rather than dispatching on publication kind.

Arendt owns input/assistant/Frame identity; Heisenberg owns Window/mount lifetime.
Both received this method claim and matched result. Accepted PR215 staging and
public installed packages remain untouched.

## Matched installed continuous journey

Actual installed Toad + SDK0.12.1 + native Pi + ACP + real UI, with one controlled
localhost provider request split into 39 delayed SSE chunks. Each run has a fresh
private root and a distinct original input; no failed input was retried.

Both runs use Core2519fb653d3dde780da729d8979b55df68026b95,
Textual65053c5a2df12249ef1c4193beeff7023c1f75d7 and native e36 manifest
(e36a1dde326b70179fa1c854a73fcad61948c90f5a93465a55ddd07d72936f07;
tree5ea25e3f9e88d073e5506ce97ceeca4c763b6da19f986ab032880d45f020f35c).
Normal declared dependencies and generated uv.lock resolve all 68 packages;
full native trust and uv pip check passed. No source override or borrowed .pth.

| Actual observation | Baseline068ac516 | Candidatec9aa8302 |
| --- | ---: | ---: |
| Native user / canonical assistant / provider request | 1 / 1 / 1 | 1 / 1 / 1 |
| Provider chunks / original answer characters | 39 / 947 | 39 / 947 |
| Samples with two Agent headers | 37 / 62 | 0 / 60 |
| Samples with context source mounted | 37 | 37 |
| Final painted response bodies / headers | 2 / 2 | 1 / 1 |
| Driver exit | 1, repeated header assertion | 0 |

The candidate's nominal new case observes the original active response resource
while source context/disclosure publishes during the held stream. The source
has not covered that answer, so its existing association remains one resource.
The complete answer and one header paint in the final actual SVG. The baseline
likewise has only one canonical assistant, proving the split is a consumer
resource error rather than two provider answers.

Receipts, actual SVGs and package provenance are in
[evidence/original-stream-headers](../../evidence/original-stream-headers).
The packaged required debt ratchet compared both production paths against
main d56f8138: exit0, no debt delta. bfabbcb8 adds only test observations;
production bytes match installedc9. Remaining proof limits: this checkpoint
covers the demonstrated continuous native/context-publication split; it does
not claim global activation or every other source/cancel/fork lifecycle.

## Custody

Original roots /home/ts/wt/cw229b03 and /home/ts/wt/cw229c04, native journals and
raw ACP evidence remain preserved. No matching fixture processes remain.
Candidate stage is the owned persistent .artifacts/installed-core421-candidate;
baseline stage is owned by the fork baseline WT. No public roots, user owners,
uncertain inputs or paid providers were changed.
