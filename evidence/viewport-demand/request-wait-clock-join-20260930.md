# Request wait observation: existing clock relation

Kepler owns this bounded read-only tooling contribution. Arendt owns Core454's
request-wait workflow and native callbacks/journal/ACP publication. Mendel453
alone writes native provider budget/adapters. Heisenberg242 retains foreground
rendering and the next meaningful physical CPU/frame journey. This contribution
creates no provider request, phase state, monitor, cache, journal or second
coordinator. Current tools remain usable without a second timing decoder.

## Existing evidence read

Original sanitized receipts, read without altering journals or processes:

- `/home/ts/wt/comms428-native-wait-custody-20260930/evidence/comms428-native-latency/provider-gap-readonly-resumed01.json`
- `/home/ts/wt/comms428-native-wait-custody-20260930/evidence/comms428-native-latency/original-readonly-timeline01.json`

The recorded assistant follows the previous tool-result journal entry after
129.898seconds. Its client message-constructor timestamp precedes its own journal
entry timestamp by129.858seconds. That constructor runs before body construction,
onPayload, serialization and transport. It is neither transport dispatch nor
provider acceptance nor first delta. Extension/listener/publication handling also
precedes append. No causal allocation of that interval is possible from these
two endpoints. The response ID remains opaque identity, never a clock.

Current installed e36 source has an awaited onPayload before transport and awaited
onResponse(status,headers) before stream iteration. Neither supplies a retained
first-delta transport clock. NativePhaseChanged carries the actual watchdog phase;
it has no historical request/headers/delta timestamps. A replacement process's
counters cannot recover the original absent trace. The later UTC/monotonic snapshot
in original-readonly-timeline01 is not a clock bracket around this request.

## Reuse, without another phase owner

The existing `tests/tools/profile_trace.py` owns the sole Chrome transition
decoder and complete stack observations. The existing recorder owns its profiler
launch witness, sampling-ready observation, physical launch epoch and kernel CPU
phase counters. Its profile-review artifact records:

- trace_origin_monotonic_bounds: original profiler exec lower bound and actual
  sampling-ready-observed upper bound;
- trace_origin_monotonic_estimate: midpoint of those same observations;
- trace_to_video_offset_seconds: that midpoint minus capture_launch_monotonic;
- alignment_nominal_uncertainty_seconds: half the bracket plus sampling interval.

For an original ProfileTrace observation with timestamp `t` microseconds, the
existing relation gives:

```
monotonic bracket = [lower + t / 1_000_000, upper + t / 1_000_000]
video estimate   = t / 1_000_000 + trace_to_video_offset_seconds
```

Sampling interval and scheduler error remain limitations. Chrome observations
are changed stacks, not event durations, sample counts, CPU time or exact input
times. A stack whose timing bracket overlaps a request phase boundary is
ambiguous; do not assign it to one phase by a guessed midpoint. Kernel CPU
snapshots continue to own CPU deltas. No timeline report may convert an open
Chrome span into provider/local blocked time.

Arendt's original typed request/turn observations can select an interval from
this existing relation and attach their canonical identities to its full stack
and physical artifact evidence. Decode those records once through their owner;
do not copy provider phase names into a tool family or manufacture missing
headers/delta events from UI text. Native, ACP and publication stages must retain
their observation-site meanings, especially first transport delta versus first
delta consumed after asynchronous local callbacks.

Node hrtime, performance.now and Python monotonic timestamps are not declared
interchangeable by a field name. A native monotonic domain needs an original
measured binding to the recorder domain, or native observations must carry an
original wall/monotonic bracket with its uncertainty. Do not use a later clock
sample to conceal a missing historical binding. Per-request attempts remain
distinct even if one durable user turn contains several provider requests.

## Concrete next handoff

Arendt supplies the declared request/turn identities and transport/consumer clock
record contract. Mendel supplies any required existing adapter observation
capability; this worker does not modify those thirteen native source files.
Then join the existing records to ProfileTrace and phase artifacts using the
relation above. Add a bounded helper API only if the actual contract needs it;
the public observations API already exposes all retained stack points.

Arendt owns controlled local transport delay versus blocked local publication
and, if necessary, the single authorized actual selected Sol OFF fork prompt.
This worker makes no duplicate request or replay. All23902 same-run CPU/pixel
joins are already pushed;242's physical work remains active independently.

## Defined producer checkpoint review

Arendt454 cdfedfc46b8385c2b2471c6ffa47eb7d65d6ee8f now declares RequestProgress
through the existing PiPayload/FieldCodec boundary. Its original requestId,
sessionId, inputId, native hrtime observation, elapsed/callback counters and
transport stage are emitted by NativeRequestObservation. Core diagnostics retain
the exact TurnLeaseFence and this original record. No tool-side record family or
stage roster is required. Native message_update callbacks accumulate bounded
measurements without emitting a timing record for every chunk.

Request-local native monotonic spans can be reviewed immediately. Python's
PublicationMeasurements maximum start/end use Python monotonic and can be joined
to the existing profile relation immediately. Neither requires a fabricated
cross-clock offset. Callback counters measure awaited wall spans, not CPU or
provider duration; cumulative totals are not necessarily independent additive
work if callbacks become nested or concurrent.

Concrete review issue sent directly to Arendt: record_request_progress samples
`received_monotonic_ns` at diagnostic append, after the native_phase consumer's
registry reads and any preceding queued work. It is not RPC byte arrival or
decode time. Rename it to the actual record-site meaning, without an alias, or
carry a timestamp captured at the existing sole ingress owner. Publication
counters are recorded before the current transition and describe prior completed
transport spans; a cumulative maximum must not be attributed to the current
request without its original interval and identity.

The record currently has no original native process/clock-domain witness. A
matching existing RPC operation can provide one without a provider request:
Python monotonic sampled before writing the operation, native hrtime sampled in
its original matching response, Python monotonic after reading that response.
Those bounds enclose the native sample and bound the offset. The witness must
retain the actual original native process identity and request/turn fence; it
must not use a response from a replacement process or a new clock command.
One-way append time supplies only a receipt-side bound and cannot establish a
clock offset or identify where preceding delay occurred.

Controlled transport-delay and blocked-local-publication checks can first be
distinguished within their own original clocks. Cross-clock native/provider/UI
allocation remains unavailable until a measured original witness exists. The
single actual selected Sol OFF fork, if needed, remains Arendt's sole custody.

## Video-origin limit established on original242/02 artifacts

The original recorder starts FFmpeg before sampling `capture_launch_monotonic`.
It does not retain the timestamp of the first acquired video frame. The formula
above therefore yields a nominal video estimate, not a certified first-frame
clock binding. The profiler-origin bracket and sampling interval do not bound
that additional acquisition offset. Do not use them for sub50ms key-to-paint,
frame-gap or native/request causal allocation. Ordinary phase markers also
include screenshot/export and driver work; B-ready is stamped after the visible
history wait. Source-backed observer assessment is retained in
`physical242-original-clock-assessment-20260930.{md,json}`. Native workflow
checks and inspected phase endpoints remain valid independently of this missing
fine timing witness. No later/replacement clock observation can repair it.
