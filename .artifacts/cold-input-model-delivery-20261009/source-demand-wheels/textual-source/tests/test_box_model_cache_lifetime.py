from fractions import Fraction

from textual.app import App
from textual.geometry import Size
from textual.widget import Widget
from textual.widgets import Static


async def test_obsolete_measurement_revisions_are_released_without_losing_width_reuse():
    app = App()
    async with app.run_test() as pilot:
        widget = Static("wrapped text " * 30)
        await app.mount(widget)
        await pilot.pause()
        fraction = Fraction(1)
        widths = (30, 60, 90)

        def measured(width):
            return widget._get_box_model(Size(width, 20), app.size, fraction, fraction)

        previous_models = ()
        for index in range(12):
            widget.update("changed paragraph " * (index + 1))
            widget.styles.padding = (0, index % 3)
            await pilot.pause()
            models = {width: measured(width) for width in widths}
            for width, model in models.items():
                assert measured(width) is model, "Same-revision width result should remain reusable"
            assert not any(
                widget._box_model_cache.get(key)[0] is previous
                for key in tuple(widget._box_model_cache.keys())
                for previous in previous_models
            ), "Unreachable previous-generation box models retained"
            previous_models = tuple(models.values())


async def test_ancestor_measurements_remain_correct_after_child_layout_changes():
    app = App()
    async with app.run_test() as pilot:
        leaf = Static("first")
        container = Widget(leaf)
        container.styles.height = "auto"
        await app.mount(container)
        await pilot.pause()
        before = container._layout_updates
        old_height = container.size.height
        fraction = Fraction(1)
        old_box = container._get_box_model(Size(80, 20), app.size, fraction, fraction)
        leaf.update("line\n" * 12)
        await pilot.pause()
        assert container._layout_updates > before
        assert container.size.height > old_height
        new_box = container._get_box_model(Size(80, 20), app.size, fraction, fraction)
        assert new_box.height > old_box.height
        assert not any(
            container._box_model_cache.get(key)[0] is old_box
            for key in tuple(container._box_model_cache.keys())
        )


async def test_cached_box_return_restores_its_original_alignment_constraints():
    app = App()
    async with app.run_test() as pilot:
        child = Static("box")
        child.styles.width = 4
        child.styles.height = 1
        parent = Widget(child)
        parent.styles.width = "auto"
        parent.styles.height = "auto"
        parent.styles.min_width = "50%"
        parent.styles.align_horizontal = "center"
        await app.mount(parent)
        await pilot.pause()

        fraction = Fraction(1)
        first = parent._get_box_model(Size(80, 20), app.size, fraction, fraction)
        original_extrema = parent._extrema
        second = parent._get_box_model(Size(160, 20), app.size, fraction, fraction)
        assert (first.width, second.width) == (40, 80)
        assert parent._extrema.min_width == 80

        assert parent._get_box_model(Size(80, 20), app.size, fraction, fraction) is first
        assert parent._extrema is original_extrema
        # The arrangement resource may retire independently of retained boxes.
        # Its native alignment must consume the selected box's original bounds.
        parent._clear_arrangement_cache()
        arrangement = parent.arrange(Size(40, 20))
        placement = next(entry for _, entry in arrangement.placements if entry.widget is child)
        assert placement.region.x == 18


async def test_fixed_box_retains_local_source_while_children_change():
    app = App()
    async with app.run_test() as pilot:
        leaf = Static('first')
        container = Widget(leaf)
        container.styles.width = 20
        container.styles.height = 4
        await app.mount(container)
        await pilot.pause()
        fraction = Fraction(1)
        def measured():
            return container._get_box_model(Size(80, 20), app.size, fraction, fraction)
        first = measured()
        revision = container._layout_updates
        leaf.styles.height = 12
        assert container._layout_updates > revision
        assert measured() is first
        added = Static('added')
        await container.mount(added)
        assert measured() is first
        await added.remove()
        assert measured() is first
        container.styles.padding = 1
        assert measured() is not first
        assert measured().width == 20
        container.styles.width = 30
        assert measured().width == 30
        assert container._get_box_model(Size(80, 20), app.size, fraction, fraction,
            constrain_width=True).width == 30


async def test_replaced_native_style_source_does_not_reuse_equal_epoch():
    app = App()
    async with app.run_test() as pilot:
        first, replacement = Widget(), Widget()
        first.styles.width = 20
        first.styles.height = 4
        replacement.styles.width = 30
        replacement.styles.height = 4
        await app.mount(first, replacement)
        await pilot.pause()
        assert first.styles._cache_key == replacement.styles._cache_key
        fraction = Fraction(1)
        def measured():
            return first._get_box_model(Size(80, 20), app.size, fraction, fraction)
        assert measured().width == 20
        original = first.styles
        first.styles = replacement.styles
        try:
            assert measured().width == 30
        finally:
            first.styles = original
        assert measured().width == 20


async def test_fractional_width_is_local_only_for_greedy_native_boxes():
    app = App()
    async with app.run_test() as pilot:
        widget = Static('first')
        widget.styles.width = '1fr'
        widget.styles.height = 4
        await app.mount(widget)
        await pilot.pause()
        fraction = Fraction(30)
        def measured(greedy):
            return widget._get_box_model(Size(80, 20), app.size, fraction, fraction,
                                        greedy=greedy)
        greedy = measured(True)
        intrinsic = measured(False)
        widget.update('a substantially longer original line')
        changed = measured(False)
        assert changed.width > intrinsic.width
        assert measured(True) == greedy
        # After switching measurement sources, acquire the fixed/fractional
        # source again; subsequent content mutations need not retire it.
        greedy = measured(True)
        widget.update('another changed line')
        assert measured(True) is greedy


async def test_custom_scalar_keeps_descendant_measurement_source():
    from textual.css.scalar import Scalar, Unit
    leaf = Static('source')
    leaf.styles.height = 2

    class ChildWidth(Scalar):
        def resolve(self, size, viewport, fraction_unit=Fraction(1)):
            return Fraction(leaf.styles.height.value)

    app = App()
    async with app.run_test() as pilot:
        container = Widget(leaf)
        container.styles.width = ChildWidth(1.0, Unit.CELLS, Unit.WIDTH)
        container.styles.height = 4
        await app.mount(container)
        await pilot.pause()
        fraction = Fraction(1)
        def measured():
            return container._get_box_model(Size(80, 20), app.size, fraction, fraction)
        assert measured().width == 2
        leaf.styles.height = 8
        assert measured().width == 8


async def test_custom_style_getter_keeps_descendant_measurement_source():
    from textual.css.scalar import Scalar
    from textual.css.styles import RenderStyles

    class ChildStyles(RenderStyles):
        @property
        def width(self):
            return Scalar.from_number(self.node.children[0].styles.height.value)

    app = App()
    async with app.run_test() as pilot:
        leaf = Static('source')
        leaf.styles.height = 2
        container = Widget(leaf)
        container.styles.height = 4
        await app.mount(container)
        await pilot.pause()
        original = container.styles
        container.styles = ChildStyles(container, original.base, original.inline)
        fraction = Fraction(1)
        def measured():
            return container._get_box_model(Size(80, 20), app.size, fraction, fraction)
        try:
            assert measured().width == 2
            leaf.styles.height = 8
            assert measured().width == 8
        finally:
            container.styles = original
