# Channels update fanout

## Implemented

SessionTracker publishes SessionChangedEvent for a title, subtitle or project
path change, initial admission and close. MainScreen consumes the original
SessionTitleChanged/SessionSubtitleChanged/SessionPathChanged declarations and
updates that tracker. SessionsTabs still consumes those metadata changes.
ChannelsSidebar passes the same notification to SidebarObservation.

Previously that observation projected the saved wire snapshot and republished
the whole channel hierarchy for every notification. The channel row content,
unread/activity, membership and orders come from CoordinationSnapshot and
ThreadRowsWork, not the tab title/subtitle/path. SidebarSnapshot derives only
the current thread-to-tab routes from these local sessions. ChannelGroup uses
those routes for actual row navigation and selected state.

SidebarProjection now owns sync_sessions. Under its existing publication lock,
it projects the latest retained wire snapshot and rebuilds only when those
routes change. A title-only notification therefore cannot start a full row
publication, or overwrite a newer backend snapshot with a pre-lock copy.
SidebarObservation keeps normal navigation reconciliation and backend refresh.
Backend revisions, explicit thread actions, real route changes and currentness
still use their existing owners. No cache, registry, timer or budget was added.

## Source trace and scope

The existing refactor-audit Package parsed all 288 Toad production modules with
zero omissions. Read the SessionTracker writers, MainScreen metadata handlers,
SessionsTabs consumer, SidebarObservation publication paths, SidebarSnapshot,
SidebarProjection, ChannelGroup/SidebarGroup, ThreadRowsWork, relationship
source/invalidation and canonical Core revision/roster/relationship readers.
Changed source and the affected pilot compile; git diff --check passes.

This branch starts from merged main c28d4a333 plus the already published sidebar
parking fix. The selected live 437e source differs in sidebar preparation and
relationship parking; it is not claimed equal to this source App. The private
App uses the retained d846 Core source and the existing isolated Textual source,
not an installed/current-live artifact qualification. No package, public input,
provider, SDK or borrowed holder operation occurred.

## Running private App evidence

Actual producer: private Comms declarations and Messaging.send_initial_cohort.
Twenty-four original declared threads committed 96 messages in four bursts.
Six actual native session surfaces were acquired through SessionAdmissions;
one was subsequently closed through its original lifetime. Both sidebars were
open; relationship source identity/root were bound to that original private
wire. Five relationship groups observed all 96 messages. Seven channel groups
retained all 144 native thread rows across the bursts.

Six authored tab-title changes went through SessionTracker, independently of
backend messages. Native monitoring recorded six route reconciliations and no
row rebuild or preparation from those metadata notifications. Four actual
channel publications and eight relationship refreshes processed the backend
bursts. Existing source reads, row paint and real session close passed. The
original source App and its fixture cleanup joined with exit 0.

Result: /home/ts/.cache/agent-scratch/hsf08/result.json
Raw stdout/stderr and original launcher handle:
.artifacts/sidebar-update-fanout-20261006/after-relationships.*
Pilot: tests/sidebar_update_fanout_pilot.py

Measured event-loop gaps: maximum 193 ms, p95 51 ms (10 ms diagnostic sampler).
Backend commit plus observed publication took 3.10-3.44 seconds per burst.
Those are headless source-App observations, not terminal frames, live provider
streaming, or an overall speedup. The simultaneous-response hang is not yet
qualified as fixed. This change removes the demonstrated metadata-to-roster
work while preserving actual backend updates and relationship source reads.

## Limits and preserved negatives

Initial cProfile and py-spy measurements were unusable: overlapping worker
profiling produced invalid inclusive timings; sampling fell behind and altered
the private App lifetime. They supply no causal or speed claim. Their raw files
remain in the same artifact directory and private hsf01/hsf02 roots.

Recipient diagnostics hsf03-hsf05 confirmed retained Conversation widgets, but
command-discovery counts were absent. SourcePublicationRequests retires all
Conversation observations of CoordinationAccess during resume/cancel. Thus
zero command counts do not prove cheap command discovery or hidden-reader
fanout. That distinct source lifetime issue was not patched here.

The first changed check (hsf06) incorrectly expected no global preparation
during metadata updates. A legitimate backend expiry refresh also ran. Its
failure remains preserved. The corrected diagnostic counts the actual local
route rebuild branch rather than suppressing expiry or changing production.
hsf07 passed; hsf08 adds the necessary bound, visible relationship coverage.
No earlier buffering acceptance was repeated.

Remaining work: attribute the remaining multi-thread update stalls in the real
source/event/queue path, then qualify actual simultaneous live responses after
coherent integration. Parent's frame-preparation and Arendt's native Screen
cohort remain separate owners. This patch is source implemented and exercised;
installation and live multi-agent acceptance remain outstanding.

## Service replacement refusal

Reviewed the complete SidebarObservation.service writes: initialization, mount,
and bind. bind holds SidebarProjection.lock while replacing the service and
clearing snapshot/read identity/navigation. The reset protects snapshot custody.
sync_sessions now also preserves the original service-bound refusal in publish:
it captures the original service before waiting and rejects replacement after
acquiring the lock. No reset/republication race is claimed as demonstrated.
This is a borrowed identity, not retained state. Changed source
compiles and diff check passes; no App or prior acceptance was repeated.
