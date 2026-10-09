"""Width style decisions consume the original class-bound measurement supply."""
from textual._measurement import NATIVE_WIDGET_WIDTH
from textual.widget import Widget


def test_leaf_width_style_decision_reads_container_once():
    class Counted(Widget):
        reads = 0

        @property
        def is_container(self):
            self.reads += 1
            return super().is_container

    leaf = Counted()
    leaf.reads = 0
    assert NATIVE_WIDGET_WIDTH.styles_sensitive(leaf)
    assert leaf.reads == 1
