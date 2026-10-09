# Native width declaration supply

Layout.get_content_width arranges at zero height: incoming height is unused,
but arrangement styles still matter. Its original HeightDependency declaration
now owns both answers through NativeOptimalWidth. The separate consumer override
in NativeWidgetWidth is deleted; shared NativeWidgetMeasurementHeight selects
container/leaf once and consumes the original compiled layout declaration.

IndependentHeight remains conservative about styles. Undeclared arrangers and
custom width methods still receive ContextHeight from Layout.__init_subclass__;
explicit custom declarations retain their own policies. Box and relative-height
resources, epochs, descendants, placement and raw style publication are unchanged.

Four affected checks passed in 0.46 seconds: one container acquisition for a
live custom getter, original native paint/raw writes, height-independent custom
layout hooks retaining style inputs, and unknown layout/scalar behavior.
Before/after AST covers 724/725 modules with zero omissions and all width
supply/style/measurement consumers. There is no competing runtime writer of
Layout._content_width_dependency; it remains class-declaration-owned.

The original loaded source Toad App passed with ten tabs, 508 widgets, zero
inputs/providers and empty stderr. Pointer first-display medians were 33.9 ms
on each side (maxima 80.2/64.0 ms). Original cProfile native is_container calls
were 453/270, versus 506/303 in retained prior source App profiles. These are
observed calls, not compressed Chrome transitions or a controlled timing trial.
app.json preserves raw profile rows/hashes; stdout/stderr are retained here;
original profiles remain at
/home/ts/.cache/agent-scratch/native-width-supply-app-20261007.

Production is unchanged from a2056caa4. Private declaration-table replacement
outside Layout.__init_subclass__ is not certified; normal custom methods and
C3 subclass declarations still bind their original policy or conservative
ContextHeight. This does not change box/relative source validity or cache reuse.
No package/public operation or reliable overall latency gain. The actual
agent-switch and ACP costs remain separate unresolved workflows.
