# Native line-surface measurement inputs

ScrollView measures its authored virtual_size, whose original Reactive writes
already request layout. Its two methods now declare that source through the
existing HeightDependency family. Computed or replaced virtual_size access and
undeclared method overrides remain context-sensitive.

Original ScrollBarRender changes colors without changing cell extent. ScrollBar
and its Blank corner now supply that fact through the existing renderer hook.
The live instance renderer is checked; custom renderers/wrappers stay opaque.
This completes the virtual-child supply which made the earlier ScrollView-only
candidate ineffective. No descendant traversal, style epoch, placement update,
refresh callback, size mutation or arrangement fence is bypassed.

Four distinct affected checks passed: mounted Log/TextArea paint preservation
and extent retirement; native container-only resize; computed/replaced extent
and undeclared width/height methods; custom scrollbar classes and live method
replacement. The two first authored failures incorrectly treated RichLog as
having the same width declaration as ScrollView and then checked only its
height policy. Its genuine width override stays conservative; raw failures
remain in checks-first.log and checks.log. No producer was broadened to pass.

The final existing source Toad App completed at production 8e1547f62 with ten
tabs, 508 widgets, zero inputs/providers and empty stderr. Actual pointer
sidebar first-display medians were 33.5/34.8 ms (maxima 100.9/65.0 ms).
app.json records original cProfile call/duration measurements and profile
hashes; raw output is retained here. This is headless completed display, not
terminal pixels, an agent-switch comparison or an installed latency claim.
The earlier prototype App remains at
/home/ts/.cache/agent-scratch/native-line-measurement-app-20261007; final source
App profiles remain at native-line-measurement-app02-20261007 in the same
scratch parent. The final guard correction narrowed custom class/instance
supply; it did not alter native rendered dimensions or style publication.

The original recursive traversal and every true geometry mutation remain.
Subclasses of ScrollBar/Corner stay conservative because extra descriptors can
independently alter shape. Base instances also check live bound methods and
renderer selection; no per-event result is retained. Original reactive access
supply distinguishes computed from stored extent without duplicating discovery.
AST parses 724 native production/test modules with zero omissions, covering
all dependency, source-access, renderer and invalidation consumers.

No package/public operation or reliable overall speed claim. The actual agent
mount delay and expensive arrangements remain unresolved; this change retires
an unnecessary native measurement dependency rather than suppressing layouts.
