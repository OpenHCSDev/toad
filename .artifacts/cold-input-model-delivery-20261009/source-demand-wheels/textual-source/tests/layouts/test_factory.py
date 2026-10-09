import pytest

from textual.layouts.factory import MissingLayout, get_layout
from textual.layouts.vertical import VerticalLayout
from textual.layouts.horizontal import HorizontalLayout
from textual.layouts.grid import GridLayout


def test_get_layout_valid_layout():
    layout = get_layout("vertical")
    assert type(layout) is VerticalLayout


def test_get_layout_invalid_layout():
    with pytest.raises(MissingLayout):
        get_layout("invalid")


def test_document_declaration_supply_tracks_c3_namespace_changes():
    class Left(VerticalLayout):
        pass

    class Right(VerticalLayout):
        pass

    class Diamond(Left, Right):
        pass

    layout = Diamond()
    original = layout.document_key()
    assert original[0] is Diamond
    assert type(layout.acquire_document()) is Diamond
    Right.arrange = HorizontalLayout.arrange
    with pytest.raises(TypeError, match="detached layout inputs"):
        layout.document_key()
    # Left masks Right only when it actually owns the declaration.
    Left.arrange = VerticalLayout.arrange
    assert layout.document_key() == original
    del Left.arrange
    with pytest.raises(TypeError, match="detached layout inputs"):
        layout.document_key()
    del Right.arrange
    assert layout.document_key() == original


def test_document_supply_tracks_actual_base_change_and_instance_binding():
    class Reparented(HorizontalLayout):
        pass

    layout = Reparented()
    previous = layout.document_key()
    Reparented.__bases__ = (VerticalLayout,)
    current = layout.document_key()
    assert current != previous
    assert current[0] is Reparented
    # An instance function is unbound, even if it is the original class object.
    layout.arrange = VerticalLayout.arrange
    with pytest.raises(TypeError, match="instance-specific"):
        layout.document_key()
    del layout.arrange
    assert layout.document_key() == current


def test_document_supply_does_not_require_cooperative_subclass_hook():
    class StopsSubclassHook(VerticalLayout):
        def __init_subclass__(cls, **kwargs):
            pass

    class Leaf(StopsSubclassHook):
        pass

    assert Leaf().document_key()[0] is Leaf


def test_foreign_mixin_requires_its_own_detached_contract():
    class Foreign:
        pass

    class UnknownMutationOwner(Foreign, VerticalLayout):
        pass

    with pytest.raises(TypeError, match="detached layout inputs"):
        UnknownMutationOwner().document_key()


def test_unobserved_metaclass_mutation_cannot_inherit_native_admission():
    class DirectSetter(type(VerticalLayout)):
        def __setattr__(cls, name, value):
            type.__setattr__(cls, name, value)

    class Unobserved(VerticalLayout, metaclass=DirectSetter):
        pass

    with pytest.raises(TypeError, match="detached layout inputs"):
        Unobserved().document_key()
    assert VerticalLayout().document_key()[0] is VerticalLayout


def test_document_key_reads_current_grid_configuration_without_republishing_supply():
    layout = GridLayout()
    implementation = type(layout)._document_implementation
    original = layout.document_key()
    layout.min_column_width = 8
    assert layout.document_key() != original
    assert type(layout)._document_implementation is implementation
    acquired = layout.acquire_document()
    assert acquired.min_column_width == 8
    assert acquired.document_key() == layout.document_key()
