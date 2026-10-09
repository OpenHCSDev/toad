# One layer inheritance decision in Widget, one native traversal

Same finished checkout normally joined Text51/main2fac. Source first: Widget.layers
and Compositor._arrange_root.get_layers independently choose the outermost authored
layer declaration. The compositor additionally maintains inherited_layers for every
visited node and recursive resolver custody until the scene completes.

Extend existing Widget behavior to resolve its authored declaration against the
original inherited order. Public layers and native layout traversal use that same
behavior. Carry original resolved order through existing add_widget/arrange_widget,
removing the recursive get_layers algorithm, per-pass inheritance map and duplicate
public selection. Preserve subtree key order, external-root ancestry, explicit empty
and default layer declarations, custom layers property behavior, detached nodes,
placement order, capture/projection lifetime and custom override context.

No new cache/map/type/flag/registry, no Toad edits, WT/env/native copy or film.
NRA Package AST covers entire native/Toad/tools roots before editing; omissions
and dynamic limitations explicit. Original420 ProfileTrace arrangement activation
is source context, not callcounts/CPU time/dominance. Batch affected native sanity
last, then one changed joined installed journey owned by Heisenberg; no unchanged
51 capture or physical speed claim. Full performance remains active.

## Published implementation and final native controls

Production `6b4326827d9258875f973af61390dee746966c81`: Widget and Compositor,
54 added / 27 deleted lines against merged51. Existing Widget owns
`_inherit_layer_order`; public `layers` and the native tree traversal consume
it. `_get_layer_order` acquires external-root ancestry once, using the original
Widget/App boundary and traversal order. The transient optional tuple means
an actually absent authored declaration, retaining the original optional
contract; it is not a new durable/runtime state or mirror. Explicit empty and
duplicate tuples are preserved exactly by the public property. Native rank
mapping is a derived synchronous resource, projected only when a declaration
is reached and shared through descendants. Custom `layers` overrides remain
local arrangement policy, preserving the original raw inherited key semantics.

Deleted the independent compositor resolver and recursion, all its callers,
per-widget inherited-order registry and completion cleanup; deleted public
Widget's separate declaration-choice loop. Original subtree key rank snapshot,
scene map, clip/placement/capture publication and custom property dispatch
remain their existing contracts. No new class/map/cache/state field. Root
public acquisition still requires inspecting ancestry to find the outermost
source; its temporary ordered ancestor sequence is not a semantic registry.

Whole roots before: native249/26 relevant sites, Toad288/0, tools41/0,
zero omissions. Native after249/31 sites, zero omissions; sole authored
inheritance choice is Widget._inherit_layer_order. Added sites are shared
owner methods and traversal parameters, not independent decisions. Full search
has no get_layers declaration/caller in current source; original GC control
now names the actual two recursive arrangement closures. Other `.layers`
reads are Styles declarations or Compositor front-to-back order, semantically
separate resources. Dynamic external overrides are not resolved by AST.

Final batched native controls: **21 passed in 1.94s**, real App/compositor and
subtree resources, covering outermost inheritance/change, custom property,
empty/duplicate public names, detached Widget default/declaration, nested
capture with external ancestor, clipping/scroll/retention/invalidation, and
recursive closure release without GC. No production changes after this batch;
no old51/420 controls or film repeated. Resource warning with12.3GiB available
RAM supported this single short existing-dependency process; no memory caps,
new environment, native copies, installed writes or provider calls.

**Source-qualified draft; installed changed-path qualification pending** the
next meaningful joined Heisenberg workflow. No CPU gain, dominance, smoothness,
physical FPS or 144Hz claim. Existing 51/420 original evidence remains frozen.

## Original joined422 installed qualification

**Scoped installed Ready for review**, using corrected native53a52e5b/wheela805
which includes this unchanged52source. Original installed App contracts passed
retained A/B/A/editorUndo/shellclose, native left/right pointer+slider sidebar
controls, rapidcoldPageDown/End and bounded preparation/runway. Original physical
seven input checks and drag/scroll/Up/Down/reverse/End completed.

The actual raw journey **FAILED** at peer click: the target was clipped outside
the captured roster after sidebar-up, although sidebar-down showed it. No16warm
or full physical A/B/A/Undo/IRC pass. Both raw completed flags remainFALSE; no
replay, new movie or oracle relaxation. Original owner identity unchanged; owned
cleanup remaining/errors empty; transferredUI custody/encoder255 preserved.
All14original keeper hashes matched; source proof records exact339Core/319Toad/
266Text/3Diff files, Core611d416/native2ea/SDK.12.1/normal69.

Heis reviewed actualUp52.7559..53.5559DURING originalUI; Down/reverseAFTER.
Kepler personally reviewed18-8SIDEBAR32.2385..33.0385 while sameUI alive,
notUp; earlier personal-up filenames are corrected by original live_review
phase. Selected bands show painted body/chrome with repeatedpositions/stepped
movement. Up writer23.05median/63.44p95/205.67worstms; Down13.22/27.12/
222.82; observer-inclusiveCPU76.06/64.23%, unmatched workloads. No causal
gain/smoothness/FPS/144Hz claim. Last10s idle zero viewport churn is separate
from full idle marker18.60%UI. Fullnativeperformance remainsactive.

F0 main normally integrated WITHOUT native source change. Required Debt ratchet
must pass before merge; this installed receipt cannot waive any growth. Full
native suite remainsdeferred. Existing holder/code imports handed back toSchF1;
no ongoing borrowed package/App/client/native claim from this qualification.

## F0 correction: one source fold and one carried resource

Parent's original packaged ratchet against main919 reported Compositor +7 and
Widget +20. This supersedes the earlier source-qualified assessment; original
installed422 evidence does not waive growth and remains unchanged.

Widget._get_layer_order now folds supplied original sources in native leaf-to-root
order, keeping the last (outermost) authored declaration. Public layers supplies
its lazy ancestry; root acquisition supplies the same traversal; descendant
admission supplies its one local source only while no ancestor declaration owns
rank order. The same behavior handles explicit empty orders and the Widget/App
boundary. Public duplicate names remain exact; rank projection preserves their
last ordinal. Custom layers property dispatch remains local arrangement policy.

Deleted _inherit_layer_order, the temporary ancestry list/reverse walk and every
layer_names parameter/caller. Native traversal carries only the original derived
rank mapping; cache keys snapshot that resource. No new type, registry, map,
compatibility path or policy change. The corrected property documentation describes
the actual outermost contract; no unrelated class behavior is removed to offset
metrics. Relative main919, Widget has no class-span growth and Compositor shrinks
by two lines. Before/after packaged ratchet and changed App controls remain the
final required confirmation, not a source-only Ready claim.
