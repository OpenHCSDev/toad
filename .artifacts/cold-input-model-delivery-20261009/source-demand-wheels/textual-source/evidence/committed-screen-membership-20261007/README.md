# Committed screen membership

Widget.is_on_screen declares last-screen-update membership. It previously used
Compositor.find_widget, which acquires missing offscreen paths and can arrange
again every time a hidden widget asks. It now consumes the original committed
map via _get_published_geometry. No membership store or negative cache is added.
Region, virtual_region and focus ordering retain their original acquisition.
The selected capture reader remains unchanged; screen membership describes the
committed screen, not a temporary body-render scope.

Native automatic_refresh and Toad project/path/recovery status consumers are
covered by the existing property. Custom overrides remain independent. The Toad
throbber already explicitly selects clipped visible membership; that stricter
paint eligibility remains untouched. The source census is in source.json.

One actual headless App control passed in 0.37 seconds: visible, offscreen,
hidden and detached cases, 120 reads with zero _arrange_root calls, followed by
successful explicit offscreen acquisition. Original native layout and widget
owners were used. No provider, package, public runtime or profile rerun.

This removes status-query arrangement. It does not fix repeated unsatisfied
focus geometry requests, prove the recorded mount delay solved, or establish
an installed latency improvement. Child cardinality is already constant-time;
style invalidation retains custom renderer dependencies.
