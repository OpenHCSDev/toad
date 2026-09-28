# Structural frame-pipeline investigation

Status: source investigation and controlled scaling probes complete. The
recommended change is a persistent workspace with explicit session-state and
bounded presentation lifetimes. This PR contains the probes and design; it does
not claim that the runtime scalability defect has already been fixed.

## User acceptance priorities

Worst-case stalls, their frequency, and scalability take priority over reducing
an already-stable 30–40 ms median. Eliminating quadratic retained presentation
cost is a required outcome, not an optional micro-optimization.

The implementation must be cleanly nominal and polymorphic: explicit ownership
and lifecycle types, behavior selected through declared methods, and reuse of
existing typed navigation/focus/history contracts. Avoid class-name/string
dispatch, capability-fallback chains, and duplicated source authority. Global UI
has one owner; session data lifetime and rich presentation lifetime must be
separable. Any new abstraction must remove a concrete ownership/update mismatch.

## Fixed baseline

- Toad main `43e57c91e9643cfab053630e1d5aaadd12cffad9`.
- Textual main `16ede007c34bec893b2dbedb3999223381129678`.
- Core `3996e820157b674f456974c1a8417de4776e1279`.
- CPython 3.14.2, normal GC policy; serial bounded fixtures, 4 GiB/no-swap caps.
- Existing final captures: `toad-pr108-landing-navigation` and
  `toad-pr108-landing-filters`. Their manifests carry source/runtime identities.
- Other active work owns recursive watcher startup (#109) and core/L0A migration
  (#107 and core #229). This investigation owns neither worktree nor deployment.

## Questions to resolve

1. Does a tab represent an entire retained application screen when only its
   conversation and thread-local state actually differ? Which global controls
   are still replicated, and how does their cost scale with tab count?
2. Which state changes invalidate geometry, text layout, paint, or source data?
   Are those ownership boundaries aligned, or does a small update fan out through
   unrelated ancestors and siblings?
3. Which phases publish geometry during a navigation/hydration transaction? How
   much work comes from explicit layout, resume/resize handling, queued timers,
   and geometry reads that synchronously rebuild derived maps?
4. How much of the cost is visible content, and how much is inactive widget/task/
   cache lifetime? Would a different representation remove work, or merely move
   it into cold activation?
5. Where does input acknowledgment sit relative to frame preparation and paint?
   Which delays are UI CPU, worker completion, GC, or terminal flush?

## Falsifiable hypotheses and controls

| Hypothesis | Structural evidence / probe |
| --- | --- |
| Global chrome is duplicated per screen | Ownership census and tab-count scaling with fixed source cohort |
| First-revisit preparation catches up duplicated controls | Measure tab reconciliation/mount counts separately; account for any work deliberately performed earlier |
| Reparenting invalidates too broad a scene | Native style/layout call counts, changed style rules, parent invalidation and geometry publication |
| Layout/hydration boundaries cause repeated work | Record causes and phase ordering, separating explicit navigation layout from subsequent callbacks |
| Retained history dominates the collector's live graph | Empty vs populated history with fixed viewport; active/inactive ownership census and ordinary GC observations |
| Rendering visible content is intrinsically dominant | Exclusive UI-thread spans and content/viewport scaling; separate collector pauses from render CPU |

Diagnostic counterfactuals must be labeled as such. Moving work earlier is not a
reduction in total work. Headless presentation is not native terminal latency.
Inclusive spans are not additive. GC trigger stacks are not heap ownership.

## Required decision output

- Source-backed ownership and update-flow map.
- Comparable probe receipts, including adverse outcomes and measurement overhead.
- Ranked architectural options, invariants and migration scope.
- A specific next change with a falsifiable acceptance boundary, plus evidence
  identifying tempting changes that would only improve a local minimum.

## Findings

### 1. A tab currently owns another copy of the application UI

The data owner is already global: `SessionTracker` and `ToadApp.open_tabs`.
Nevertheless, MainScreen, CommsScreen, pending screens and file previews compose
their own `SessionsTabs`. Each strip holds a label and close-button widget for
every open tab. `SessionsTabs._reconcile_tabs` deliberately leaves inactive strips
stale, then catches each up when its screen becomes active.

Source: `src/toad/widgets/session_tabs.py:175-334`, `screens/main.py:207-234`,
`screens/session_view.py:279-300`, and `session_tracker.py:101-179`.

With a fixed source cohort, the following **empty-conversation** results were
measured. N is the number of exercised tabs; each fixture also has its original
owner tab and one prepared loading screen. Counts are after all exercised tabs
have caught up, and include hidden registered widgets.

| N | Label widgets | Close-button widgets | Registered widgets | Active-screen widgets |
| ---: | ---: | ---: | ---: | ---: |
| 4 | 23 | 23 | 849 | 273 |
| 16 | 275 | 275 | 2,929 | 298 |
| 32 | 1,059 | 1,059 | 6,593 | 330 |
| 64 | 4,163 | 4,163 | 16,993 | 394 |

The exercised strips account for `N * (N + 1)` labels; the fixture's unvisited
owner/prepared strip adds three in these runs. The close buttons duplicate the
same pattern. This is an ownership-derived quadratic count, not an extrapolation
from a few noisy timing samples. At N=64, first revisits mount another **1,953
labels plus 1,953 close buttons** merely to reconcile copies of one global list.

The global preparation cache is working: those first revisits report cache hits.
But a hit still hashes/materializes a result for a consumer, and every per-screen
consumer must create its own widgets. Making that cache faster would retain the
quadratic construction/storage obligation.

### 2. The worst case exists without long history

Same 64-thread source cohort, eight peers, two exact fixture channels, fixed
110x37 headless viewport and ordinary GC:

| N | First-revisit median/max | First revisits >100 ms | Warm forward median/max | Largest observed GC |
| ---: | ---: | ---: | ---: | ---: |
| 4 | 48.97 / 49.44 ms | 0/3 | 38.02 / 40.04 ms | 4.21 ms |
| 16 | 56.62 / 132.19 ms | 1/15 | 41.38 / 46.10 ms | 71.73 ms |
| 32 | 71.74 / 103.47 ms | 1/31 | 54.14 / 77.17 ms | 0.02 ms |
| 64 | 116.50 / 249.52 ms | 55/63 | 76.01 / 111.66 ms | 322.30 ms |

The 64-tab run's largest loop gap was **382.78 ms**; three first-revisit intervals
and four warm-forward intervals had loop gaps over100ms. Its final census had
**2,048,217 tracked objects**, while the active screen still had394 widgets.
The non-monotonic GC maxima at16/32 are why a single maximum is not a reliable
frequency estimate. Runs have unequal sample counts and are not long-duration
percentile certification. They establish a scaling failure, not a universal bound.

One strict64-tab run failed the existing stale-roster-layout assertion on first
return to session45: a layout saw46 labels while65 were desired. It failed before
writing a final JSON result; the journal preserves the failure. A follow-up used
the existing `--observe` mode to retain diagnostics through the whole workload;
that run reported zero stale layouts. This timing-sensitive boundary is unresolved,
and the follow-up is not retroactive proof that the failed run was correct.

### 3. Widgets are expensive actors, including inactive decorative controls

Textual's `MessagePump._start_messages` starts a task for every registered widget.
`_process_messages` retains its context and awaits its message loop, which awaits
the queue. The64-tab census immediately after creation contained approximately
**68,336 coroutine objects and14,050 tasks**, alongside13,083 registered widgets.
It also contained per-widget queues, events, locks, contexts, style maps and caches.

Source: Textual `message_pump.py:585-681`, `widget.py` initialization and
`screen.py:1315-1325`. Heap type counts include other runtime objects and are not
transitive ownership measurements. The source explains the per-widget actor cost;
the census shows how large the surrounding graph becomes.

Even deleting duplicate labels/close buttons alone would leave roughly8,797
registered widgets in the64-tab case, before accounting for other header nodes.
Thus sharing another bar is a useful migration slice, but not the final scalability
architecture. Full inactive composer/goal/menu/sidebar trees remain heavyweight.

### 4. Shared navigation still receives a per-screen initialization cycle

The current activation path is:

```text
App.switch_mode
  capture reader/navigation intent
  mount/init destination mode
  SharedChannels.attach -> Widget.reparent -> native styles + parent invalidation
  native mode switch / Resume
  SessionView.prepare_navigation
    restore bar geometry
    clear shared roster's navigation_ready
    catch up this screen's SessionsTabs
  layout_navigation -> root reflow
  present_navigation -> paint / flush receipt
  shared roster hydration callback -> cached projection
  CommsSidebar._finish_navigation -> whole-screen layout, optionally scroll layout
  resize / underline / footer / body callbacks -> further update work
```

`CommsSidebar.prepare_navigation` clears readiness on every activation.
`_finish_navigation` then explicitly calls `screen._refresh_layout`, even when the
retained roster was already complete and its cached projection did not change.
This is a mismatch between **source readiness, presentation lifetime and host
activation**. They should have distinct owners/contracts.

Source: `app.py:930-961`, `widgets/channels_sidebar.py:48-88`,
`widgets/comms_sidebar.py:524-573`, `screens/session_view.py:279-326`.

The empty warm-return probes repeatedly record **four reflows and one FooterKey
mount per switch**, despite zero tab-label changes. Detailed16-tab probes restyle
93 nodes on every transfer with a median of **zero changed native rule maps**.
That rule-map comparison is diagnostic only: unchanged own rules do not prove
unchanged inherited paint state, transforms, focus or selector context. It does
not authorize blindly skipping stylesheet application.

In the detailed16-tab empty probe, warm `_sync_tabs` median was about0.15ms and
`prepare_navigation` about1.6–2.1ms, while the whole switch remained42–47ms. First
revisits had much larger reconciliation/worker-delivery spans. So duplicated tab
catch-up explains a major cold-tail mechanism but not all warm work.

### 5. Geometry reads can publish another whole derived map

Textual `Compositor.full_map` rebuilds the whole map when invalidated and clears
the viewport map. `Widget.region` / `virtual_region` can reach it. The recorded
native opening traces include such calls from `SessionsTabs.update_underline`,
scroll-to-center, cursor refresh and terminal updates.

Source: Textual `_compositor.py:553-569`, `screen.py:1339-1425`,
Toad `widgets/session_tabs.py:205-229`.

The architecture needs an explicit distinction between **reading committed
geometry** and **requesting new geometry**. Existing APIs promising fresh geometry
must remain correct; silently making getters stale is not a fix. A persistent
workspace also prevents a header-local change from being coupled to a completely
different screen's geometry context.

### 6. Current history bounding is useful, but presentation still churns

At four tabs and a fixed viewport, increasing each synthetic initial snapshot
from5 to100 source records kept the registered widget count at**879** and retained
fragment-view count at**16** after revisits. Prepared result bytes increased as
expected; the full UI did not scale with all100 records. This is evidence in favor
of retaining the existing source-backed history/window machinery.

However, each rich warm return remounted **11 Markdown/code presentation children**
and submitted two RenderPreparation jobs. The16-tab trace recorded30 such jobs
per15-switch warm pass, with no new source history. Rich warm returns had6–8
reflows instead of the empty fixture's4.

`DocumentViewport._reconcile` keeps warm bodies only while the owning screen is
current; it empties that retained set for inactive screens. That keeps memory down
but makes each return reconstruct presentation. Increasing the per-view allowance
indiscriminately trades this for more retained heap. The appropriate owner is an
application-wide bounded presentation pool, separate from durable/session state.

Source: `widgets/viewport_body.py:99-138`, `screens/session_view.py:52-62`, and the
existing `ViewportBody` / `HistoryAnchor` contracts.

### 7. View construction also creates resources that were never used

The64-empty-tab process group contained65 shell children. This is source-backed:
`Conversation.initialize_view` accesses `self.shell` unconditionally, and that
property creates and starts a PTY subprocess. Shell output can then mount a hidden
ShellTerminal and query geometry.

Source: `widgets/conversation.py:2455-2505,3032-3052`, `shell.py:213-301`.

This is another lifecycle mismatch: opening a conversation implies activating an
optional shell capability. It belongs to an explicit session resource owner and
activation operation, independent of mounting the conversation surface. Watcher
startup is separately owned by #109, which merged during this investigation;
these fixed-baseline probes do not include it.

## Recommended nominal architecture

### Owner boundaries

```text
WorkspaceScreen (persistent native Screen)
  WorkspaceChrome (one header, Channels presentation, binding-aware footer)
  SessionViewport (bounded set of active/warm SessionSurface leases)

SessionTracker / existing navigation declarations
  SessionController per open logical view (lightweight)
    existing Agent/history/source authority, referenced rather than copied
    owned editor/view intent
    explicit optional resource lifetimes
```

The names below describe responsibilities, not a parallel metadata registry:

| Nominal owner | Responsibility |
| --- | --- |
| `WorkspaceScreen` | Native focus, modal stack, frame coordination and `Screen.active_bindings` authority |
| `WorkspaceChrome` | One projection of existing global tab/sidebar state; unchanged ownership across session switches |
| `SessionController` | Session lifetime and typed operations; current authoritative state survives presentation retirement |
| `SessionSurface` | Rich UI for a selected controller; implements activation, intent capture and retirement polymorphically |
| `PresentationPool` / `PresentationLease` | Tunable global bounds on rich UI, plus attachment-generation protection for asynchronous work |
| Typed editor/view state | Actual document/undo/selection/filter/anchor state, moved out of widget-only lifetime rather than duplicated |

Native, history/channel/direct, file and provisional-opening controllers implement
the same surface lifecycle. Their existing typed `NavigationTarget` / history
declarations choose behavior at the serialized boundary. The workspace does not
switch on class names, string kinds or optional-method presence.

The minimal contract shape is explicit (design sketch, not implemented runtime):

```python
class SessionController(ABC):
    @abstractmethod
    def create_surface(self, host: SessionViewport) -> SessionSurface: ...

    @abstractmethod
    async def close_view(self) -> None: ...  # Client/view lifetime, not StopOwner.


class SessionSurface(Widget, ABC):
    @abstractmethod
    async def activate(self, lease: PresentationLease) -> None: ...

    @abstractmethod
    def capture_view_state(self) -> SessionViewState: ...

    @abstractmethod
    async def release_presentation(self) -> None: ...
```

Concrete controllers construct their concrete surfaces directly. The pool uses
these methods uniformly; it does not discover behavior through method probes.
`SessionViewState` must be a typed family of actual UI intent, not an arbitrary
dictionary of widget fields or a duplicate of protocol state.

Do not reuse `SessionPresentation` as the rich UI type: that name already denotes
a small fallback label/status value in `session_tracker.py`. Keep `SessionSurface`
as the distinct nominal UI lifetime.

### Critical contracts

1. **One source owner.** Move genuine state ownership out of Conversation where
   necessary; do not keep a controller copy and an independently authoritative
   widget copy. Agent/core messages update their session controller even while its
   surface is absent. The visible surface observes only its current lease.
2. **Source freshness and host activation are different.** A host switch does not
   make an unchanged global roster unready. Real route changes still validate and
   retire stale results through the canonical owner. Geometry publication has its
   own native revision/receipt, not a fabricated source revision.
3. **Bounded presentation, preserved intent.** Draft text alone is insufficient:
   undo state, cursor/selection, filters and source-keyed scroll anchors must survive
   retirement. An unbounded exception for selected/focused hidden widgets would
   invalidate the scalability claim; logical selection must become independent of
   those widget identities before claiming a hard bound.
4. **Ordinary native routing.** SessionSurface uses native widget focus/bindings and
   existing nominal navigation/focus contracts. `Screen.active_bindings` stays the
   authority. Close-view, release-presentation and stop-owner retain their distinct
   semantics; presentation eviction cannot stop a durable execution owner.
5. **Explicit resource activation.** Shells/watchers/transports are managed by their
   actual session/project owners. An unused shell does not start because a surface
   was composed. Adopt #109's existing watcher work rather than duplicate it.
6. **Visible-work budget.** Use one tab-list model with viewport-bounded rendering
   as tab counts grow. Offscreen logical tabs are small data records, not another
   set of actors in every inactive screen.

### Migration order and why

1. Establish the controller/surface ownership contract and move editor/view state
   to its actual owner. Keep the existing concrete session implementations behind
   that contract while preserving all route, input, draft and close semantics.
2. Move global chrome into one persistent WorkspaceScreen. Session switching
   changes the selected surface/lease, not the parent of the global navigation
   tree. Eliminate per-screen tab-list catch-up and shared-roster readiness resets.
3. Bound inactive rich surfaces with a global pool and make optional resources
   demand-driven. Reuse current history paging/body abstractions and typed
   preparation services; avoid rebuilding canonical source state.
4. Make geometry publication explicit at the workspace frame boundary and scope
   local scroll/paint invalidation. Only then reassess the remaining Textual
   per-widget actor overhead and visible text rendering cost.

This is an incremental migration of owners, not a second UI implementation behind
fallback chains. Each stage needs paired correctness and scaling evidence.

## Alternatives that fail the stated goal

| Alternative | Why it is insufficient |
| --- | --- |
| Another cache around per-screen tab synchronization | Every consumer still owes its own N controls; cached materialization and mounting remain quadratic |
| Reparent one shared tab strip between existing full screens | Removes quadratic label storage, but leaves thousands of inactive widgets, per-transfer styling and split frame/readiness ownership; useful only as a migration step |
| Retire every hidden screen immediately | Loses widget-owned state or moves the spike into reconstruction unless controller/state ownership is separated first |
| Retain all Markdown bodies to avoid remounts | Trades rebuild work for an unbounded live graph across tabs; violates the global presentation budget |
| Skip CSS/layout whenever own rules look equal | Ignores inherited state, geometry, focus and selector context; the diagnostic equality is not a correctness proof |
| Tune/freeze/disable GC | Does not remove the object graph or scaling obligation, and can conceal rather than solve the tail |
| Start by rewriting Textual's actor scheduler | Potential long-term value, but broad semantic risk; first stop retaining irrelevant UI and duplicating global ownership |

## Falsifiable acceptance gates for implementation

- At4/16/32/64 logical tabs with a fixed source cohort: exactly one workspace
  header/Channels owner, linear lightweight tab records, and viewport/global-budget
  bounded rich widgets. No `N*N` label or close-button growth.
- First revisit must not create controls for every other tab. Unchanged warm
  activation must not reinitialize global source readiness or mount unrelated UI.
- Exercise repeated/random tab switching, source updates, route replacement,
  resize, blocked hydration, selection, pending input, close/cancel and modal focus.
  Verify draft/undo/selection/anchor and backend ownership preservation.
- Measure first/revisit/warm separately, with loop stalls and input acknowledgments
  over100/250ms counted explicitly. Run enough repetitions to compare spike
  frequency; do not substitute median improvement or one observed maximum for a
  worst-case claim.30–40ms steady behavior is acceptable at this stage.
- Test blocked source IO and optional-resource startup independently of UI frames.
  Loading feedback and navigation remain responsive while those owners work.
- Restore strict stale-layout/paint/identity assertions at scale. The observed
 64-tab assertion failure must be diagnosed rather than hidden by `--observe`.
- Fresh native-terminal validation follows the headless structural probes. Python
  GC policy remains ordinary; private user previews and installations are untouched.

## Reproduction and receipt index

Probe: `tests/many_tabs_return_pilot.py`; report tool:
`tools/performance/analyze_frame_structure.py`. New parameters vary tab count and
history size while `--source-threads` keeps source inventory constant.

```sh
python tests/many_tabs_return_pilot.py --empty --tabs 16 --source-threads 64 \
  --peers 8 --channels 2 --gc-observe --ownership-census --output "$CAPTURES/scale-16.json"
python tools/performance/analyze_frame_structure.py "$CAPTURES/scale-16.json"
```

Use the recorded exact source/core environment and the serial4GiB/no-swap runner.
Run `--trace` separately: it copies style dictionaries and captures nested call
spans, so its timing is attribution evidence, not ordinary acceptance timing.
Censuses run outside timed switches and never force collection. `--gc-census`
(the older DEBUG_SAVEALL mode) was **not used** in this investigation.

- `toad-structural-{empty,rich}-{4,8,16}-r2.json`: six successful baseline cases,
  fixed24-source-thread cohort. Source probe hash/provenance is in each result.
- `toad-structural-{empty,rich}-{4,16}-trace1.json`: four detailed attribution runs.
- `toad-structural-scale-{4,16}-r3.json`: successful strict cases,64-source cohort.
- `toad-structural-scale-64-r3.service` journal: strict stale-layout assertion
  failure,79.17s,397.6MiB; no completed JSON result.
- `toad-structural-scale-{32,64}-observe1.json`: completed diagnostic continuations,
 61.90/284.00s,248.5/490.1MiB. Both reported zero stale layouts on those attempts.
 The shell wait timed out while64 continued in its owned systemd unit; the unit
 subsequently completed normally and its receipt was read.
- `toad-structural-history-{5,100}-r1.json`: fixed-four-tab history-size controls.
- `toad-structural-default-contract.json`: original default10-tab rich workload
  with all existing assertions enabled,18.18s,245.9MiB; validates the extended
  probe's original invocation path. Scoped Ruff and diff checks also pass.
- All owned runs completed; all reported zero swap. The user preview remained open.

The initial four-tab calibration preceded provenance fields and is superseded by
the indexed runs. A probe indentation error was caught by Ruff before execution
and fixed. No production source files were changed for these experiments.
