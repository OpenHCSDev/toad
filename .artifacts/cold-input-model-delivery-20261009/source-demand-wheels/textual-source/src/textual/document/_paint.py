"""Native document geometry and paint, without scene or message-pump admission."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction
from types import MappingProxyType, MethodType
from typing import TYPE_CHECKING, Callable, Iterable
from weakref import ref

from rich.style import Style as RichStyle
from rich.palette import Palette
from rich.terminal_theme import TerminalTheme

from textual._arrange import arrange
from textual._compositor import Compositor, RootSceneClip
from textual._extrema import Extrema
from textual._styles_cache import StylesCache
from textual.box_model import BoxModel
from textual.content import Content
from textual.css.styles import RenderStyles, Styles
from textual.css.stylesheet import Stylesheet
from textual.dom import DOMNode
from textual.geometry import NULL_OFFSET, NULL_SPACING, Offset, Region, Size, Spacing
from textual.layout import Layout, WidgetPlacement
from textual.map_geometry import MapGeometry
from textual.layouts.vertical import VerticalLayout
from textual.selection import SELECT_ALL, Selection
from textual.strip import Strip, StripRenderable
from textual.style import Style
from textual.visual import RenderOptions, Visual

if TYPE_CHECKING:
    from textual.filter import LineFilter
    from textual.layout import DockArrangeResult
    from textual.document._markdown import MarkdownSourceBlock


class StyleContext(DOMNode):
    """An acquired declaration and selector state, separate from live custody."""

    def __init__(self, declaration, *, pseudo_classes=frozenset(), **kwargs):
        self.declaration = declaration
        self._document_pseudo_classes = pseudo_classes
        super().__init__(**kwargs)
        # Original detached Styles already own validation without scene
        # notification when node=None. RenderStyles still owns inheritance.
        self._css_styles = Styles()
        self._inline_styles = Styles()
        self.styles = RenderStyles(self, self._css_styles, self._inline_styles)

    @property
    def _parent(self):
        reference = self.__dict__.get("_document_parent")
        return None if reference is None else reference()

    @_parent.setter
    def _parent(self, parent):
        # Source ancestry is independent of message-pump custody and its epoch.
        self._document_parent = None if parent is None else ref(parent)

    def _make_component_node(self, component):
        return StyleContext(DOMNode, classes=component)

    @property
    def style_type(self):
        return self.declaration

    def bind_declaration(self, declaration):
        self._document_declaration = declaration
        self._css_types = declaration.selector_names

    def _is_style_type(self, declaration):
        captured = self.__dict__.get("_document_declaration")
        return (
            declaration in captured.python_bases
            if captured is not None
            else issubclass(self.declaration, declaration)
        )

    @property
    def _component_style_scope(self):
        captured = self.__dict__.get("_document_declaration")
        return (
            self.declaration._component_style_scope
            if captured is None
            else captured.component_scope
        )

    @property
    def css_type_names(self):
        captured = self.__dict__.get("_document_declaration")
        return (
            self.declaration._css_type_names
            if captured is None
            else captured.type_names
        )

    @property
    def css_type_name(self):
        captured = self.__dict__.get("_document_declaration")
        return (
            self.declaration._css_type_name if captured is None else captured.type_name
        )

    def _selector_type_names(self):
        return self.declaration._selector_type_names()

    @property
    def _node_bases(self):
        captured = self.__dict__.get("_document_declaration")
        return (
            self.declaration._css_bases(self.declaration)
            if captured is None
            else captured.bases
        )

    def _get_component_classes(self):
        captured = self.__dict__.get("_document_declaration")
        return (
            self.declaration._get_component_classes()
            if captured is None
            else captured.component_classes
        )

    def has_pseudo_classes(self, class_names):
        return class_names <= self.get_pseudo_classes()

    def has_pseudo_class(self, class_name):
        return class_name in self.get_pseudo_classes()

    def get_pseudo_classes(self):
        return set(self._document_pseudo_classes)

    @property
    def _pseudo_classes_cache_key(self):
        return frozenset(self.get_pseudo_classes())


class DocumentNode(StyleContext):
    """One acquired native declaration in an immutable document.

    These nodes have native CSS ancestry and use native layouts, box resolution
    and paint. They never register with an App, start a message pump, mount a
    widget, or read scene geometry. A declaration supplies content and children;
    arbitrary widget methods are not invoked on this different resource.
    """

    _component_style_scope = True

    def __init__(
        self,
        declaration: type[DOMNode],
        content: Content | None = None,
        *,
        children: Iterable[DocumentNode] = (),
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        expand: bool = False,
        shrink: bool = False,
        pseudo_classes: frozenset[str] = frozenset(),
        scroll_offset: Offset = NULL_OFFSET,
        source_range: tuple[int, int] | None = None,
        source_index: int | None = None,
        pre_layout: Callable | None = None,
        process_layout: Callable | None = None,
        inline_rules: dict | None = None,
        auto_links: bool = True,
        selection: Callable = Visual.selected_text,
    ) -> None:
        self.content = content
        self.expand = expand
        self.shrink = shrink
        self.scroll_offset = scroll_offset
        self.source_range = source_range
        self.source_index = source_index
        self._prepare_layout = pre_layout
        self._process_layout = process_layout
        self.auto_links = auto_links
        self.selection = selection
        self.text_selection = None
        self._document_selection_style = None
        self.selecting = False
        self._extrema = Extrema()
        self._region = Region()
        self._default_layout = VerticalLayout()
        self._styles_cache = StylesCache()
        super().__init__(
            declaration,
            pseudo_classes=pseudo_classes,
            name=name,
            id=id,
            classes=classes,
        )
        if inline_rules:
            self._inline_styles = Styles(
                _rules=Styles(_rules=inline_rules).acquire_document_rules()
            )
            self.styles = RenderStyles(self, self._css_styles, self._inline_styles)
        for child in children:
            self.add(child)

    def add(self, child: DocumentNode) -> None:
        child._attach(self)
        self._nodes._append(child)

    def get_pseudo_classes(self) -> set[str]:
        # Ordered and empty state belongs to this complete source cohort, not
        # the preceding mounted scene. Other state is explicitly acquired.
        result = set(self._document_pseudo_classes)
        result.discard("empty")
        if self.is_empty:
            result.add("empty")
        if not isinstance(self.parent, DocumentNode):
            return result
        positions = {
            "first-of-type": self.first_of_type,
            "last-of-type": self.last_of_type,
            "first-child": self.first_child,
            "last-child": self.last_child,
            "odd": self.is_odd,
            "even": self.is_even,
        }
        result.difference_update(positions)
        result.update(name for name, present in positions.items() if present)
        return result

    @property
    def layout_viewport(self) -> Size:
        return self.presentation.viewport

    @property
    def layout_screen_size(self) -> Size:
        return self.presentation.screen_size

    @property
    def is_container(self) -> bool:
        return bool(self._nodes) or self.styles.layout is not None

    @property
    def layout(self) -> Layout:
        return self.styles.layout or self._default_layout

    @property
    def layer(self) -> str:
        return self.styles.layer or "default"

    def _get_document_layer_order(self):
        order = None
        for node in self.walk_ancestors(with_self=True):
            if not node._component_style_scope:
                break
            if node.styles.has_rule("layers"):
                order = node.styles.layers
        return order

    absolute_offset = None

    @property
    def uses_screen_coordinates(self) -> bool:
        return self.styles.has_any_rules("constrain_x", "constrain_y")

    @property
    def show_vertical_scrollbar(self) -> bool:
        return False

    @property
    def show_horizontal_scrollbar(self) -> bool:
        return False

    @property
    def _has_relative_children_height(self) -> bool:
        return self._scan_relative_children_height(False)[0]

    def pre_layout(self, layout: Layout) -> None:
        """Declarations with preparation effects override this source method."""
        if self._prepare_layout is not None:
            self._prepare_layout(self, layout)

    def process_layout(self, placements):
        return (
            placements
            if self._process_layout is None
            else self._process_layout(placements)
        )

    @property
    def layout_invalidated_widgets(self):
        # This is a fresh immutable source, never a partially updated scene.
        return self.children

    @property
    def scrollable_content_region(self):
        return (
            self.content_region if self.region else Size(self._layout_width, 0).region
        )

    def arrange(self, size: Size, optimal: bool = False) -> DockArrangeResult:
        self._layout_width = size.width
        return arrange(self, self.children, size, self.layout_viewport, optimal)

    def _resolve_extrema(self, container, viewport, width_fraction, height_fraction):
        return Extrema.resolve(
            self.styles,
            container,
            viewport,
            width_fraction,
            height_fraction,
        )

    def _get_box_model(
        self,
        container,
        viewport,
        width_fraction,
        height_fraction,
        constrain_width=False,
        greedy=True,
    ) -> BoxModel:
        model, self._extrema = BoxModel.resolve(
            self,
            container,
            viewport,
            width_fraction,
            height_fraction,
            constrain_width,
            greedy,
        )
        return model

    def get_content_width(self, container: Size, viewport: Size) -> int:
        self._layout_width = container.width
        return self._measure_content_width(container, viewport)

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        self._layout_width = width
        return self._measure_content_height(container, viewport, width)

    def _parse_visual_style(self, style: str):
        return self._document_stylesheet.parse_style(style)

    def _render(self):
        return self.content if self.content is not None else self._render_container()

    def render(self):
        return self._render()

    @property
    def region(self) -> Region:
        return self._region

    @property
    def content_region(self) -> Region:
        return self.region.shrink(self.styles.gutter)

    def render_lines(self, crop: Region) -> list[Strip]:
        content_size = self.content_region.size
        visual = self._render()
        if isinstance(visual, StripRenderable):
            # Native Canvas already owns these complete keyline rows. No Rich
            # console or scene widget is required to render them a second time.
            lines = list(visual._strips)
        else:
            lines = visual.render_strips(
                content_size.width,
                content_size.height,
                self.visual_style,
                RenderOptions(
                    self._get_style,
                    self.styles,
                    self.text_selection,
                    self._document_selection_style,
                ),
            )
        lines = Visual.format_strips(
            lines,
            *content_size,
            self.visual_style,
            link_style=(
                self.link_style
                if self.auto_links and not self.is_container and not self.selecting
                else None
            ),
            content_align=self.styles.content_align,
        )
        blank = Strip.blank(content_size.width, self.visual_style.rich_style)
        base_background, background = self.background_colors
        strips = self._styles_cache.render(
            self.styles,
            self.region.size,
            base_background,
            background,
            lambda y: lines[y] if y < len(lines) else blank,
            self.presentation.filters,
            None,
            None,
            content_size=content_size,
            crop=crop,
            opacity=self._resolved_paint_state().opacity,
            ansi_theme=self.presentation.ansi_theme,
            native_ansi=self.presentation.native_ansi,
        )
        if not self.is_container:
            identity = RichStyle.from_meta({"document_leaf": self.paint_leaf_index})
            strips = [strip.apply_style(identity) for strip in strips]
        return strips


def _input_value(value):
    """Freeze actual native value inputs, never scene epochs or CSS guesses."""
    # These exact native leaves already ARE their immutable acquisition.
    # Keep subclass/custom copy semantics and mutable input validation below.
    if value is None or type(value) in (bool, int, float, str, bytes):
        return value
    if isinstance(value, Layout):
        return value.document_key()
    if isinstance(value, TerminalTheme):
        return (type(value), _input_value(vars(value)))
    if isinstance(value, Palette):
        return (type(value), _input_value(value._colors))
    if isinstance(value, dict):
        return tuple((key, _input_value(item)) for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_input_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_input_value(item) for item in value)
    return deepcopy(value)


@dataclass(frozen=True)
class StyleInput:
    declaration: type[DOMNode]
    type_names: frozenset[str]
    type_name: str
    selector_names: frozenset[str]
    bases: tuple[type[DOMNode], ...]
    python_bases: tuple[type, ...]
    component_classes: frozenset[str]
    component_scope: bool
    name: str | None
    id: str | None
    classes: str
    pseudo_classes: frozenset[str]
    base_rules: dict
    inline_rules: dict
    components: tuple
    key: tuple

    @staticmethod
    def current_admission(
        node: DOMNode, *, pseudo_classes: frozenset[str] | None = None,
        _inputs: dict | None = None,
    ) -> tuple:
        """Acquire this actual CSS participant, sharing only within one borrow."""
        if _inputs is not None and node in _inputs:
            return _inputs[node]
        inputs = (
            id(node),
            type(node),
            node._parent_revision,
            node.styles._cache_key,
            None if node.styles.layout is None else node.styles.layout.document_key(),
            node.id,
            node.name,
            node.classes,
        )
        get_pseudo_classes = node.get_pseudo_classes
        # Keep the original observation order: custom getters can change the
        # inputs read above. Their full call and dynamic behavior stay live.
        observed = frozenset(
            get_pseudo_classes(restrict=pseudo_classes)
            if isinstance(get_pseudo_classes, MethodType)
            and getattr(get_pseudo_classes.__func__, "_document_restrict", None)
            is get_pseudo_classes.__func__
            else get_pseudo_classes()
        )
        inputs = (*inputs, observed)
        if _inputs is not None:
            _inputs[node] = inputs
        return inputs

    @classmethod
    def acquire(cls, node: DOMNode, *, source_root: bool = False):
        # Ancestors supply their actual effective rules. The constructed root's
        # base/component rules belong to the acquired stylesheet, evaluated
        # against its source children, rather than the preceding host tree.
        base = {} if source_root else node.styles.base.acquire_document_rules()
        inline = node.styles.inline.acquire_document_rules()
        components = (
            ()
            if source_root
            else tuple(
                (
                    name,
                    style.base.acquire_document_rules(),
                    style.inline.acquire_document_rules(),
                )
                for name, style in sorted(node._component_styles.items())
            )
        )
        pseudo_classes = frozenset(node.get_pseudo_classes())
        if source_root:
            pseudo_classes -= {"empty"}
        values = (
            node.style_type,
            node.css_type_names,
            node.css_type_name,
            node._css_types,
            tuple(node._node_bases),
            tuple(node.style_type.__mro__),
            node._get_component_classes(),
            node._component_style_scope,
            node.name,
            node.id,
            " ".join(sorted(node.classes)),
            pseudo_classes,
            _input_value(base),
            _input_value(inline),
            _input_value(components),
        )
        return cls(*values[:12], base, inline, components, values)

    def make(self):
        node = StyleContext(
            self.declaration,
            name=self.name,
            id=self.id,
            classes=self.classes,
            pseudo_classes=self.pseudo_classes,
        )
        node.bind_declaration(self)
        node._css_styles = Styles(
            _rules=Styles(_rules=self.base_rules).acquire_document_rules()
        )
        node._inline_styles = Styles(
            _rules=Styles(_rules=self.inline_rules).acquire_document_rules()
        )
        node.styles = RenderStyles(node, node._css_styles, node._inline_styles)
        # Component styles retain their original attached virtual-node meaning.
        from textual.css.stylesheet import _ComponentStyles

        for name, base, inline in self.components:
            component = node._make_component_node(name)
            component._attach(node)
            component._css_styles = Styles(
                _rules=Styles(_rules=base).acquire_document_rules()
            )
            component._inline_styles = Styles(
                _rules=Styles(_rules=inline).acquire_document_rules()
            )
            component.styles = RenderStyles(
                component, component._css_styles, component._inline_styles
            )
            node._component_styles[name] = _ComponentStyles(component)
        return node


@dataclass(frozen=True)
class DocumentPresentation:
    """Exact acquired style and terminal inputs, independent of widget lifetime."""

    ancestors: tuple[StyleInput, ...]
    root: StyleInput
    declarations: tuple[StyleInput, ...]
    stylesheet: Stylesheet
    viewport: Size
    screen_size: Size
    ansi_theme: TerminalTheme
    native_ansi: bool
    filters: tuple[LineFilter, ...]
    key: tuple
    admission: tuple
    ancestor_pseudo_classes: frozenset[str] | None
    """Source-declared observations in addition to actual CSS dependencies.

    None preserves full live ancestor observation for undeclared custom hooks.
    """

    @staticmethod
    def _application_admission(app, stylesheet, *, _inputs: dict | None = None) -> tuple:
        """Acquire the actual stylesheet, terminal and mutable palette inputs."""
        if _inputs is not None and app in _inputs:
            return _inputs[app]
        inputs = (
            id(stylesheet),
            id(stylesheet._rules),
            stylesheet._require_parse,
            app.viewport_size,
            app.size,
            app.theme,
            app.native_ansi_color,
            _input_value(app.ansi_theme),
        )
        if _inputs is not None:
            _inputs[app] = inputs
        return inputs

    @staticmethod
    def current_admission(
        owner, *, ancestor_pseudo_classes: frozenset[str] | None = None,
        _nodes: dict | None = None, _applications: dict | None = None,
        _pseudo_classes: Mapping[DOMNode, frozenset[str] | None] | None = None,
    ) -> tuple:
        """Original invalidation facts for this actual publication participant.

        These facts qualify repeated queries only on the same admitted scene
        lifetime. A replacement widget requires value comparison at publication;
        an equal new counter never certifies retained document paint.
        """
        app = owner.app
        stylesheet = app.stylesheet
        admission = (
            tuple(
                StyleInput.current_admission(
                    node,
                    pseudo_classes=(
                        _pseudo_classes[node] if _pseudo_classes is not None else
                        None if node is owner else ancestor_pseudo_classes
                    ),
                    _inputs=_nodes,
                )
                for node in owner.css_path_nodes
            ),
            owner._subtree_style_revision,
            *DocumentPresentation._application_admission(
                app, stylesheet, _inputs=_applications,
            ),
            tuple(
                (type(filter), type(filter).apply, _input_value(vars(filter)))
                for filter in owner.get_line_filters()
            ),
        )
        return DocumentPresentation._restrict_admission(
            admission, ancestor_pseudo_classes
        )

    @staticmethod
    def _restrict_admission(admission, ancestor_pseudo_classes):
        if ancestor_pseudo_classes is None:
            return admission
        path, *inputs = admission
        return (
            tuple(
                (*node[:-1], node[-1] & ancestor_pseudo_classes)
                for node in path[:-1]
            ) + path[-1:],
            *inputs,
        )

    @classmethod
    def acquire_admissions(
        cls, paints: Mapping[DOMNode, DocumentPaint],
    ) -> Mapping[DOMNode, tuple[DocumentPaint, tuple]]:
        """Acquire immutable admissions for one synchronous presentation borrow.

        Shared ancestors and application inputs are read once, by identity;
        each participant retains its original published paint, path, source
        revision and filters. Dependencies come from that actual worker result,
        including source-only default CSS and virtual components.
        The acquisition retains no state on the scene or presentation.

        The borrower must end or reacquire on input changes, including layout,
        source, styles, membership and mutable supplier values. In particular,
        a layout acquisition cannot certify the subsequent paint. Custom
        admission producers must also supply their batch acquisition contract.
        """
        nodes: dict[DOMNode, tuple] = {}
        applications: dict[DOMNode, tuple] = {}
        pseudo_classes: dict[DOMNode, frozenset[str] | None] = {}
        for owner, paint in paints.items():
            for node in owner.css_path_nodes:
                required = None if node is owner else paint.ancestor_pseudo_classes
                if node in pseudo_classes:
                    previous = pseudo_classes[node]
                    required = (
                        None if previous is None or required is None else
                        previous | required
                    )
                pseudo_classes[node] = required
        return MappingProxyType({
            owner: (paint, cls.current_admission(
                owner, ancestor_pseudo_classes=paint.ancestor_pseudo_classes,
                _nodes=nodes, _applications=applications,
                _pseudo_classes=pseudo_classes,
            ))
            for owner, paint in paints.items()
        })

    def current_for(
        self, owner, *, paint: DocumentPaint | None = None,
        admissions: Mapping[DOMNode, tuple[DocumentPaint, tuple]] | None = None,
    ) -> bool:
        """Check live inputs, or borrow this exact published paint's acquisition.

        Missing membership is an error. Another source/presentation cannot use
        the supplier's observations, even when its current fields happen to
        agree. A rebind must first acquire its own publication admission.
        """
        if admissions is not None:
            supplier, admission = admissions[owner]
            if paint is not None and paint is not supplier:
                return False
            paint = supplier
        if paint is not None and paint.document.presentation is not self:
            return False
        if admissions is None:
            admission = self.current_admission(
                owner, ancestor_pseudo_classes=(
                    None if paint is None else paint.ancestor_pseudo_classes
                ),
            )
        return self._restrict_admission(
            self.admission, None if paint is None else paint.ancestor_pseudo_classes
        ) == admission

    @classmethod
    def acquire(
        cls, owner, declarations, *,
        ancestor_pseudo_classes: frozenset[str] | None = None,
    ) -> DocumentPresentation:
        if ancestor_pseudo_classes is not None and not isinstance(
            ancestor_pseudo_classes, frozenset
        ):
            raise TypeError("Document ancestor observations must be a frozenset or None")
        css_path = owner.css_path_nodes
        if css_path != list(reversed(owner.ancestors_with_self)):
            raise TypeError(
                "Custom CSS and paint ancestry require an acquired document presentation"
            )
        ancestors = tuple(StyleInput.acquire(node) for node in css_path[:-1])
        root = StyleInput.acquire(owner, source_root=True)
        declarations = tuple(
            StyleInput.acquire(StyleContext(declaration))
            for declaration in sorted(
                declarations, key=lambda item: (item.__module__, item.__qualname__)
            )
        )
        stylesheet = owner.app.stylesheet.copy()
        for declaration in declarations:
            context = declaration.make()
            for path, source, specificity, scope in context._get_default_css():
                stylesheet.add_source(
                    source,
                    read_from=path,
                    is_default_css=True,
                    tie_breaker=specificity,
                    scope=scope,
                )
        filters = tuple(
            filter.acquire_document() for filter in owner.get_line_filters()
        )
        ansi_theme = deepcopy(owner.app.ansi_theme)
        key = (
            tuple(item.key for item in ancestors),
            root.key,
            tuple(item.key for item in declarations),
            tuple(stylesheet.source.items()),
            _input_value(stylesheet._variables),
            owner.app.viewport_size,
            owner.app.size,
            _input_value(ansi_theme),
            owner.app.native_ansi_color,
            tuple(
                (type(filter), type(filter).apply, _input_value(vars(filter)))
                for filter in filters
            ),
        )
        return cls(
            ancestors,
            root,
            declarations,
            stylesheet,
            owner.app.viewport_size,
            owner.app.size,
            ansi_theme,
            owner.app.native_ansi_color,
            filters,
            key,
            cls.current_admission(owner),
            ancestor_pseudo_classes,
        )

    def prepare(
        self,
        root: DocumentNode,
        width: int,
        *,
        document,
        roots,
        headings,
        root_selection=None,
        selections=None,
        selection_style=None,
        selecting=False,
    ) -> DocumentPaint:
        # Whole-widget selection has no leaf coordinates before construction.
        # A partial root range cannot be interpreted as each leaf's own offsets.
        if root_selection is not None:
            if root_selection != SELECT_ALL:
                raise ValueError("A document root selection must cover the whole widget")
            if selections is not None:
                raise ValueError("Root-wide and leaf selections are distinct inputs")
        selections = None if selections is None else dict(selections)
        if (root_selection is not None or selections) and not isinstance(
            selection_style, Style
        ):
            raise TypeError(
                "Selected document paint requires the native Visual selection style"
            )
        # Every preparation owns its mutable CSS/geometry workspace. The
        # retained result owns only strips, literal provenance and source boxes.
        stylesheet = self.stylesheet.copy()
        stylesheet.parse()
        ancestors = [item.make() for item in self.ancestors]
        for parent, child in zip(ancestors, ancestors[1:]):
            child._attach(parent)
        if ancestors:
            root._attach(ancestors[-1])
        declarations = {item.declaration: item for item in self.declarations}
        nodes = list(root.walk_children(with_self=True))
        empty_inputs = {}
        ancestor_pseudo_classes = self.ancestor_pseudo_classes
        for node in nodes:
            node.presentation = self
            node._document_stylesheet = stylesheet
            node.bind_declaration(declarations[node.declaration])
            if ancestor_pseudo_classes is not None:
                ancestor_pseudo_classes |= stylesheet.pseudo_class_dependencies(node)
            if "empty" in stylesheet._get_candidate_rules(node._selector_names)[1]:
                empty_inputs[node] = tuple(
                    (ancestor, ancestor.is_empty)
                    for ancestor in node.css_path_nodes
                    if isinstance(ancestor, DocumentNode)
                )
            stylesheet.apply(node)
            node._css_styles = Styles(
                _rules=node.styles.base.acquire_document_rules()
            )
            node._inline_styles = Styles(
                _rules=node.styles.inline.acquire_document_rules()
            )
            node.styles = RenderStyles(node, node._css_styles, node._inline_styles)
        for node, inputs in empty_inputs.items():
            if any(ancestor.is_empty != was_empty for ancestor, was_empty in inputs):
                raise TypeError(
                    "Detached CSS display changes an :empty selector input; "
                    "this dependency requires an explicit document producer"
                )
        gutter = root.styles.gutter
        content_width = max(0, width - gutter.width)
        height = root.get_content_height(
            Size(content_width, 0), self.viewport, content_width
        )
        size = Size(width, height + gutter.height)
        geometry = {}
        leaves = []
        no_clip = RootSceneClip(size.region)

        def place(
            node,
            virtual_region,
            region,
            order,
            layer_order,
            clip,
            visible,
            dock_gutter,
            inherited_layers,
            source_index,
        ):
            if not node.display:
                return
            if (visibility := node.styles.get_rule("visibility")) is not None:
                visible = visibility == "visible"
            if node.source_index is not None:
                source_index = node.source_index
            node.paint_source_index = source_index
            node._region = region
            content_region = region.shrink(node.styles.gutter)
            total_region = content_region.reset_offset
            layers = inherited_layers
            if layers is None:
                if (names := node._get_document_layer_order()) is not None:
                    layers = {name: index for index, name in enumerate(names)}
            if node.is_container:
                if (
                    node.styles.scrollbar_gutter == "stable"
                    and node.styles.scrollbar_size_vertical
                ):
                    content_region, _ = content_region.split_vertical(
                        -node.styles.scrollbar_size_vertical
                    )
                result = node.arrange(content_region.size)
                total_region = content_region.reset_offset.union(result.total_region)
                sub_clip = clip.intersect(content_region)
                placements = WidgetPlacement.process_offsets(
                    result.placements,
                    size.region,
                    content_region.offset - node.scroll_offset,
                )
                for (
                    child,
                    local,
                    placed,
                    rank,
                    ordinal,
                    child_clip,
                ) in Compositor._place_children(
                    placements,
                    len(result.placements),
                    content_region,
                    node.scroll_offset,
                    order,
                    layer_order,
                    sub_clip,
                    no_clip,
                    layers or {"default": 0},
                ):
                    place(
                        child,
                        local,
                        placed,
                        rank,
                        ordinal,
                        child_clip,
                        visible,
                        result.scroll_spacing,
                        layers,
                        source_index,
                    )
            if visible:
                geometry[node] = MapGeometry(
                    region,
                    order,
                    clip.region,
                    total_region.size,
                    content_region.size,
                    virtual_region,
                    dock_gutter,
                    ancestors=tuple(node.walk_ancestors()),
                    gutter=node.styles.gutter,
                )
                if not node.is_container:
                    node.paint_leaf_index = len(leaves)
                    node.selecting = selecting
                    node.text_selection = (
                        root_selection
                        if selections is None
                        else selections.get(node.paint_leaf_index)
                    )
                    node._document_selection_style = selection_style
                    leaves.append(
                        DocumentLeaf(
                            source_index,
                            node.declaration,
                            node.content,
                            region,
                            content_region,
                            clip.region,
                            node.selection,
                            node.link_style,
                            node.link_style_hover,
                        )
                    )

        inherited_layers = None
        for node in reversed(ancestors):
            if node._component_style_scope and node.styles.has_rule("layers"):
                inherited_layers = {
                    name: index for index, name in enumerate(node.styles.layers)
                }
        place(
            root,
            size.region,
            size.region,
            ((0, 0, 0),),
            0,
            no_clip,
            True,
            NULL_SPACING,
            inherited_layers,
            None,
        )
        compositor = Compositor()
        mapping = compositor._paint_regions(
            compositor._ordered_geometry(geometry), size.region
        )
        chops = compositor._render_chops(
            size.region,
            compositor._regions_to_spans((size.region,)),
            widgets=mapping,
            cuts=compositor._cuts_for_regions(size.region, mapping),
            bounds=size.region,
        )
        lines = tuple(Strip.join(line.values()) for line in chops)
        placements = tuple(
            DocumentBlockPlacement(
                node.source_index,
                node.declaration,
                node.source_range,
                entry.region,
                entry.clip,
                node.id,
            )
            for node, entry in compositor._ordered_geometry(geometry)
            if node.source_index is not None
        )
        placements_by_id = {
            placement.id: placement
            for placement in placements
            if placement.id is not None
        }
        placements_by_source = {
            placement.source_index: placement for placement in placements
        }
        for member in roots:
            member.placement = placements_by_source.get(member.source_index)
        return DocumentPaint(
            size,
            lines,
            placements,
            tuple(leaves),
            document,
            self.key,
            width,
            gutter,
            root.content_region.size,
            tuple(
                DocumentHeading(entry, placements_by_id.get(entry[2]))
                for entry in headings
            ),
            root.is_empty,
            root_selection,
            None if selections is None else tuple(sorted(selections.items())),
            selection_style,
            selecting,
            roots,
            ancestor_pseudo_classes,
        )


@dataclass(frozen=True)
class DocumentBlockPlacement:
    source_index: int
    declaration: type[DOMNode]
    source_range: tuple[int, int]
    region: Region
    clip: Region
    id: str | None

    def source_text(self, document) -> str:
        from textual.widgets._markdown import MarkdownBlock

        return MarkdownBlock.source_text(document.source, self.source_range)


@dataclass(frozen=True)
class DocumentHeading:
    """One original heading entry and its actual optional native placement."""

    entry: tuple[int, str, str | None]
    placement: DocumentBlockPlacement | None


@dataclass(frozen=True)
class DocumentLeaf:
    source_index: int | None
    declaration: type[DOMNode]
    content: Content
    region: Region
    content_region: Region
    clip: Region
    selection: Callable
    link_style: RichStyle
    link_style_hover: RichStyle

    def selected_text(self, selection):
        """Use original leaf coordinates and its native copy delimiter."""
        return self.selection(self.content, selection)


@dataclass(frozen=True)
class DocumentPaint:
    """Native paint/extents and source identity, with no retained scene nodes.

    Leaf logical offsets and block regions remain separate from document paint
    rows. Interaction owners use these facts; rows aren't raw Markdown offsets.
    """

    size: Size
    lines: tuple[Strip, ...]
    blocks: tuple[DocumentBlockPlacement, ...]
    leaves: tuple[DocumentLeaf, ...]
    document: object
    presentation_key: tuple
    width: int
    """Acquired outer width, including the original root gutter."""
    gutter: Spacing
    """Actual worker-resolved native root padding and border."""
    content_size: Size
    """Intrinsic inner extent; scene allocation does not replace this answer."""
    headings: tuple[DocumentHeading, ...]
    root_empty: bool
    """Native displayed-child membership of this acquired source/style cohort."""
    root_selection: Selection | None
    """Whole-widget selection acquired before native leaves need to exist."""
    selections: tuple[tuple[int, Selection], ...] | None
    """Actual partial leaf ranges, separate from root-wide selection."""
    selection_style: Style | None
    selecting: bool
    """Original active pointer gesture, which controls native link adornment."""
    roots: tuple[MarkdownSourceBlock, ...]
    """Completed original grammar roots in source order, distinct from paint order.

    Each member retains its declaration, source index/range, original document,
    original optional fence code and actual optional placement. Consumers
    borrow this completed source; placements and composed leaves remain
    separate native geometry answers.
    """
    ancestor_pseudo_classes: frozenset[str] | None
    """Complete ancestor observations required by this prepared source and CSS."""

    @property
    def table_of_contents(self):
        return [heading.entry for heading in self.headings]

    def anchor_region(self, anchor: str) -> Region | None:
        """Use the original duplicate-aware heading slug decision."""
        from textual.widgets._markdown import Markdown

        block_id = Markdown.anchor_id_for(self.table_of_contents, anchor)
        for heading in self.headings:
            if heading.entry[2] == block_id and heading.placement is not None:
                return heading.placement.region
        return None

    def matches_selection(
        self, *, root_selection=None, selections=None, selection_style=None,
        selecting=False,
    ) -> bool:
        return self.selection_inputs == self._selection_inputs(
            root_selection=root_selection, selections=selections,
            selection_style=selection_style, selecting=selecting,
        )

    @staticmethod
    def _selection_inputs(
        *, root_selection=None, selections=None, selection_style=None,
        selecting=False,
    ):
        return (
            root_selection,
            None if selections is None else tuple(sorted(selections.items())),
            selection_style,
            selecting,
        )

    @property
    def selection_inputs(self):
        """Actual prepared selection, including absent versus empty ranges."""
        return self.root_selection, self.selections, self.selection_style, self.selecting

    @staticmethod
    def preparation_inputs(
        document, width: int, *, root_selection=None, selections=None,
        selection_style=None, selecting=False,
    ) -> tuple:
        """Rendered answer inputs, separate from participant admission.

        A rebind with equal effective presentation can use the same answer.
        An independent source acquisition or changed supplier cannot, even
        when its text is equal. Publication still requires current_for().
        """
        return (
            width, document.source_key, document.presentation.key,
            *DocumentPaint._selection_inputs(
                root_selection=root_selection, selections=selections,
                selection_style=selection_style, selecting=selecting,
            ),
        )

    @property
    def preparation_key(self) -> tuple:
        """Inputs certified by this original worker result."""
        return (
            self.width, self.document.source_key, self.presentation_key,
            *self.selection_inputs,
        )

    def matches(
        self, document, width: int, *, root_selection=None, selections=None,
        selection_style=None, selecting=False,
    ) -> bool:
        return self.preparation_key == self.preparation_inputs(
            document, width, root_selection=root_selection, selections=selections,
            selection_style=selection_style, selecting=selecting,
        )

    def is_current(
        self, owner, width: int, *, selections=None,
        admissions: Mapping[DOMNode, tuple[DocumentPaint, tuple]] | None = None,
    ) -> bool:
        """Compare current declared presentation without reading any descendants.

        The source owner must still hold this exact acquired document. A source
        replacement acquires a new MarkdownDocument; style refresh uses its
        with_presentation(). Scene eviction cannot certify different source.
        Selection and active pointer state come from their original Screen;
        a selection update never admits rows prepared for the previous input.
        admissions lends only the caller's explicit synchronous acquisition;
        omitting it keeps the original live validation.
        """
        root_selection = owner.text_selection
        return (
            width == self.width
            and self.document.presentation.current_for(owner, paint=self, admissions=admissions)
            and self.matches_selection(
                root_selection=root_selection,
                selections=selections,
                selection_style=(
                    Visual.selection_style(owner)
                    if root_selection is not None or selections else None
                ),
                selecting=owner.screen._selecting,
            )
        )

    def with_presentation(
        self, document, *, root_selection=None, selections=None,
        selection_style=None, selecting=False,
    ) -> DocumentPaint:
        """Admit retained paint after actual source/presentation value equality.

        Call at publication, including after eviction. Rows are reused only if
        their source, width, selection and effective inputs agree. The resulting resource
        owns the new participant's original invalidation witness.
        """
        if not self.matches(
            document, self.width, root_selection=root_selection, selections=selections,
            selection_style=selection_style, selecting=selecting,
        ):
            raise ValueError(
                "Retained document paint has different source, presentation or selection"
            )
        return replace(self, document=document)

    def render_lines(self, crop: Region) -> list[Strip]:
        """Borrow native rows; retain leaf logical-offset and link metadata."""
        return [
            (
                self.lines[y] if 0 <= y < self.size.height else Strip.blank(self.width)
            ).crop(crop.x, crop.right)
            for y in crop.line_range
        ]

    def get_leaf_and_offset_at(self, x: int, y: int):
        """Hit actual composed metadata; offsets belong to that original leaf."""
        if not self.size.region.contains(x, y):
            return None, None
        line = self.lines[y]
        index = line.get_style_at(x).meta.get("document_leaf")
        if index is None:
            return None, None
        return index, line.get_content_offset(x, scope=("document_leaf", index))

    def prepare_selection(
        self, selections=None, selection_style=None, *, root_selection=None,
        selecting=False,
    ):
        """Worker-side native selection styling, retaining original leaf offsets.

        Use the same source/content/CSS owners, including native tab expansion
        and wrapping. The interaction owner supplies leaf Selection values and
        the Screen's original Visual selection style; paint rows aren't source
        offsets. root_selection=SELECT_ALL applies to original leaves without
        requiring any controls or fake leaf identities to exist beforehand.
        """
        return self.document.prepare(
            self.width, root_selection=root_selection, selections=selections,
            selection_style=selection_style, selecting=selecting,
        )
