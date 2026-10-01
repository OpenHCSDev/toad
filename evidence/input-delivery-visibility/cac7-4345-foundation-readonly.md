# cac7 → 4345 foundation decode and private attestation review

Reviewer: Kepler. Implementation owner: Arendt (Core483). Parent is the sole
public executor. This review changes no product, operator or public state.

Source: `cac7bdf337d9e4dba888ce7c2093ddcc55802bc3`.
Prospective Core: `4345bfc8aac0e4717450d4f79e6fe53e331f3ccf`.
Existing target:
`/home/ts/wt/toad-s5-receiving-boundary-pair-20261001/.artifacts/runtime-s5-receiving61-20261001`.
Its activation names that Core, Toad0dd9, Textual4e9016, SDK0.12.1 and native0064.
Seven installed source files match the exact prospective Git bytes: messages,
task_decisions, field_codec, wire_record, bus_publication, compaction_records and
compaction_source. This verifies the reviewed decoder's source identity, not an
installed public release or whole user journey.

## Declaration and all affected read boundaries

`Message.decision` is **new in the target**, not a field already present in cac7.
It declares `default_factory=NoDecision` and `wire_omit_default=True`.
The original FieldCodec record decoder supplies omitted constructor defaults;
its encoder omits a field equal to its declared default factory value. Thus an
ordinary historical message decodes to NoDecision and encodes back without a
decision field. This is the single declared format and codec, not a second
legacy reader, inferred authored choice, converter or task carry (TIME-3,
TIME-8, BOUND-2).

`Message.from_committed_wire` still checks canonical equality against
`message.to_wire()`. `WireRecord.from_wire` decodes that public message once,
then delegates private rows to `CommittedDelivery.attest`. The latter still
checks the original private namespace, canonical DeliveryPolicy, root, codec,
resolver/policy versions, frozen audience and full decision digest/receipt.
Its attestation body is unchanged across the reviewed heads. New
compaction-message applicability and `FrozenAudience.includes_lookup` consume
the original frozen audience; neither rewrites its private proof.

## Existing actual source evidence, not repeated

Arendt's original certified snapshot/probe:
`/home/ts/wt/comms-retained-summary-cutover-20261001/.observations/foundation-source-proof01.json`.
Receipt SHA256:
`c8b468c89b8990dd06fc1590a0c6068e9a0bd5a302410bff077d5e177418986e`.
The original cac7 interpreter acquired one nonblocking certified source read,
retained its exact bytes and metadata in RAM, released public custody, then sent
that snapshot to the prospective interpreter's original WireScan. It completed
268 messages, 230 attested deliveries, zero silent observations and zero authored
choices; final sequence268. Original892366-byte wire snapshot SHA256:
`311b340044da876c06f5c9703d04010d6336317c39d0d9256bca02cd41ec1c89`.
Original file revision remained equal at readback. Elapsed0.804s, no public writes
or prompts. I reviewed this existing proof and source; I did not run it again.

The snapshot proves this exact historical prefix is readable and privately
attested by the target. It does not certify a later appended prefix or authorize
execution: the original stopped-owner/source fences must be revalidated at
cutover. Zero authored choices grants no permission for a later481 decision→task
conversion. That work has its separate semantic owner.

## Runtime journal is a distinct boundary

The target `SelectedSummarySource.retained` and `CompactionSource.retained` are
required declarations. The old compaction journal must not be decoded by the
target, supplied fabricated defaults or copied as enrollment. Arendt's existing
RuntimeCompactionReset retains all present named database/SQLite companions as
private fsynced opaque preimages before unlinking any, only under the original
all-stopped owner custody. It has no SQLite connection or retired-row decoder.
Original input dispositions, native sessions/proofs, prompt bindings, goals and
UNKNOWN attempts stay protected and unreplayed.

One wording correction for the current483 checkpoint document: “retains original
Message.decision format” should say “adds an omitted NoDecision default, retaining
ordinary historical public message bytes”; cac7 has no such field.

## Required fresh original typed comparison

At the owner's subsequent explicit request, one new certified snapshot was
compared with both original installed interpreters. Complete original typed
message envelopes and all private publication fields were equal: frozen audience,
full pure decision set, digest, control, resolver/policy/manifest versions, root
and keyed response receipt. Both original WireScan owners enforce admission and
sequence/publication-key uniqueness. No target Comms was initialized.

Actual receipt and runnable observer:
`foundation-wire-compare-20261001/receipt.json` and `compare.py` beside this note.
274 messages,236 private attested deliveries, final sequence274; zero silent
observations, explicit decision fields or authored choices. Every original public
envelope roundtrips exactly, with the new absent default omitted. Source908173
bytes, unchanged original revision at readback, SHA256
`1ab9de1aebea1c212a4a6d6f745a9c9c03bae77e100c398b91e80a17ba8d5d17`.
Elapsed1.329s. The missing silent observation count is explicitly absence of such
rows, not coverage of a future observation format. Zero decision→task carry.

The first diagnostic attempt is preserved in `failure01.json`: encoding the
runtime PublicWireRecord itself failed on a TYPE_CHECKING-only Message forward
annotation. This was an observer misuse, before prospective decoding. The
corrected comparison uses each canonical Message, FrozenAudience, original
decisions_wire and receipt declarations. No alternate codec, runtime record
patch or relaxed equality was introduced. No provider/user input was replayed.

No concrete foundation decode/attestation defect found. Production changes and
deletions:0. One required fresh certified public read; no new capture/provider or
public write, no journal decode, mutation, native input or replay. Direct
multi_agent_v1 coordination is unavailable in this task's active tool catalog;
the dead35901 TUI transport was not used or treated as delivery.
