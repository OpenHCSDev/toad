from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import TYPE_CHECKING

import rich.repr
from rich.text import Text

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalGroup, ScrollableContainer
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from textual.screen import Screen


@dataclass(frozen=True)
class FooterBinding:
    """Display projection of an already-resolved binding, not another key map."""

    binding: Binding
    enabled: bool
    tooltip: str
    key_display: str


@dataclass(frozen=True)
class FooterBindingGroup:
    group: Binding.Group | None
    bindings: tuple[FooterBinding, ...]


@dataclass(frozen=True)
class FooterProjection:
    groups: tuple[FooterBindingGroup, ...]
    palette: FooterBinding | None
    columns: int


@rich.repr.auto
class KeyGroup(HorizontalGroup):
    DEFAULT_CSS = """
    KeyGroup {
        width: auto;        
    }
    """


@rich.repr.auto
class FooterKey(Widget):
    ALLOW_SELECT = False
    COMPONENT_CLASSES = {
        "footer-key--key",
        "footer-key--description",
    }

    DEFAULT_CSS = """
    FooterKey {
        width: auto;
        height: 1;
        text-wrap: nowrap;
        background: $footer-item-background;
        .footer-key--key {
            color: $footer-key-foreground;
            background: $footer-key-background;
            text-style: bold;
            padding: 0 1;
        }

        .footer-key--description {
            padding: 0 1 0 0;
            color: $footer-description-foreground;
            background: $footer-description-background;
        }

        &:hover {
            pointer: pointer;
            color: $footer-key-foreground;
            background: $block-hover-background;            
        }

        &.-disabled {
            text-style: dim;
        }

        &.-compact {
            .footer-key--key {
                padding: 0;
            }
            .footer-key--description {
                padding: 0 0 0 1;
            }
        }
    }
    """

    compact = reactive(True)
    """Display compact style."""

    def __init__(
        self,
        key: str,
        key_display: str,
        description: str,
        action: str,
        disabled: bool = False,
        tooltip: str = "",
        classes="",
    ) -> None:
        self.key = key
        self.key_display = key_display
        self.description = description
        self.action = action
        self._disabled = disabled
        if disabled:
            classes += " -disabled"
        super().__init__(classes=classes)
        self.set_reactive(Widget.shrink, False)
        if tooltip:
            self.tooltip = tooltip

    def render(self) -> Text:
        key_style = self.get_component_rich_style("footer-key--key")
        description_style = self.get_component_rich_style("footer-key--description")
        key_display = self.key_display
        key_padding = self.get_component_styles("footer-key--key").padding
        description_padding = self.get_component_styles(
            "footer-key--description"
        ).padding

        description = self.description
        if description:
            label_text = Text.assemble(
                (
                    " " * key_padding.left + key_display + " " * key_padding.right,
                    key_style,
                ),
                (
                    " " * description_padding.left
                    + description
                    + " " * description_padding.right,
                    description_style,
                ),
            )
        else:
            label_text = Text.assemble((key_display, key_style))

        label_text.stylize_before(self.rich_style)
        return label_text

    def on_mouse_down(self) -> None:
        if self._disabled:
            self.app.bell()
        else:
            self.app.simulate_key(self.key)

    def _watch_compact(self, compact: bool) -> None:
        self.set_class(compact, "-compact")


class FooterLabel(Label):
    """Text displayed in the footer (used by binding groups)."""


@rich.repr.auto
class Footer(ScrollableContainer, can_focus=False, can_focus_children=False):
    ALLOW_SELECT = False
    DEFAULT_CSS = """
    Footer {
        layout: horizontal;        
        color: $footer-foreground;
        background: $footer-background;
        dock: bottom;
        height: 1;
        scrollbar-size: 0 0;
        &.-compact {
            FooterLabel {
                margin: 0;
            }
            FooterKey {
                margin-right: 1;
            }
            FooterKey.-grouped {
                margin: 0 1;            
            }
            FooterKey.-command-palette  {
                padding-right: 0;
            }
        }
        FooterKey.-command-palette  {
            dock: right;
            padding-right: 1;
            border-left: vkey $foreground 20%;
        }
        HorizontalGroup.binding-group {            
            width: auto;
            height: 1;
            layout: horizontal;
        }
        KeyGroup.-compact {            
            FooterKey.-grouped {
                margin: 0;
            }
            margin: 0 1 0 0;
            padding-left: 1;
        }

        FooterKey.-grouped {
            margin: 0 1;            
        }
        FooterLabel {
            margin: 0 1 0 0;            
            color: $footer-description-foreground;
            background: $footer-description-background;
        }

       
    }
    """

    compact = reactive(False, toggle_class="-compact")
    """Display in compact style."""
    _bindings_ready = reactive(False, repaint=False)
    """True if the bindings are ready to be displayed."""
    show_command_palette = reactive(True)
    """Show the key to invoke the command palette."""
    combine_groups = reactive(True)
    """Combine bindings in the same group?"""

    def __init__(
        self,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        show_command_palette: bool = True,
        compact: bool = False,
    ) -> None:
        """A footer to show key bindings.

        Args:
            *children: Child widgets.
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes for the widget.
            disabled: Whether the widget is disabled or not.
            show_command_palette: Show key binding to invoke the command palette, on the right of the footer.
            compact: Display a compact style (less whitespace) footer.
        """
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.set_reactive(Footer.show_command_palette, show_command_palette)
        self.set_reactive(Footer.compact, compact)
        self.set_class(compact, "-compact", update=False)
        self._binding_projection: FooterProjection | None = None
        self._binding_update_pending = False
        self._binding_revision = 0

    def compose(self) -> ComposeResult:
        if not self._bindings_ready:
            return
        projection = self._binding_projection = self._project_bindings()
        self.styles.grid_size_columns = projection.columns
        for part in projection.groups:
            if part.group is not None:
                with KeyGroup(classes="-compact" if part.group.compact else ""):
                    for item in part.bindings:
                        yield self._make_key(item, grouped=True)
                yield FooterLabel(part.group.description)
            else:
                for item in part.bindings:
                    yield self._make_key(item)
        if projection.palette is not None:
            yield self._make_key(projection.palette, palette=True)

    def _make_key(
        self, item: FooterBinding, *, grouped: bool = False, palette: bool = False
    ) -> FooterKey:
        binding = item.binding
        key = FooterKey(
            binding.key,
            item.key_display,
            "" if grouped else binding.description,
            binding.action,
            disabled=not item.enabled,
            tooltip=(
                (binding.tooltip or binding.description) if palette else
                (item.tooltip or binding.description) if grouped else item.tooltip
            ),
            classes="-command-palette" if palette else "-grouped" if grouped else "",
        )
        return key if palette else key.data_bind(compact=Footer.compact)

    def bindings_changed(self, screen: Screen) -> None:
        self._bindings_ready = True
        self._binding_revision += 1
        if not screen.app.app_focus:
            return
        if self.is_attached and screen is self.screen and not self._binding_update_pending:
            self._binding_update_pending = True
            self.call_after_refresh(self._reconcile_bindings)

    def _project_bindings(self) -> FooterProjection:
        """Capture display facts, never binding-owner widgets or bound callbacks."""
        active = self.screen.active_bindings
        by_action: dict[str, FooterBinding] = {}
        for _, binding, enabled, tooltip in active.values():
            if binding.show and binding.action not in by_action:
                by_action[binding.action] = FooterBinding(
                    binding, enabled, tooltip, self.app.get_key_display(binding)
                )
        groups = []
        for group, items in groupby(by_action.values(), lambda item: item.binding.group):
            bindings = tuple(items)
            groups.append(FooterBindingGroup(
                group if group is not None and len(bindings) > 1 else None, bindings
            ))
        palette = active.get(self.app.COMMAND_PALETTE_BINDING)
        palette_display = None
        if (
            self.show_command_palette
            and self.app.ENABLE_COMMAND_PALETTE
            and palette is not None
        ):
            _, binding, enabled, tooltip = palette
            palette_display = FooterBinding(
                binding, enabled, tooltip, self.app.get_key_display(binding)
            )
        return FooterProjection(tuple(groups), palette_display, len(by_action))

    async def _reconcile_bindings(self) -> None:
        revision = self._binding_revision
        self._binding_update_pending = True
        try:
            # Share the native recompose lock and update transaction. A direct
            # recompose must not replace children across our remove/mount awaits.
            async with self.batch():
                await self._apply_binding_projection()
        finally:
            self._binding_update_pending = False
            if (
                revision != self._binding_revision
                and self.is_attached
                and not self._closing
                and not self._pruning
            ):
                self.bindings_changed(self.screen)

    async def _apply_binding_projection(self) -> None:
        if not self.is_attached or self._closing or self._pruning:
            return
        projection = self._project_bindings()
        if projection == self._binding_projection:
            return
        previous = self._binding_projection
        same_groups = (
            previous is not None
            and len(previous.groups) == len(projection.groups)
            and all(
                old.group == new.group
                for old, new in zip(previous.groups, projection.groups)
            )
            and (previous.palette is None) == (projection.palette is None)
        )
        if not same_groups:
            await self.recompose()
            return
        parents = iter(self.children)
        for part in projection.groups:
            if part.group is not None:
                parent = next(parents)
                assert isinstance(parent, KeyGroup)
                await self._reconcile_keys(parent, part.bindings, grouped=True)
                next(parents)  # The unchanged group's description label.
            else:
                # A flat footer is the common case; grouped/flat structural
                # transitions retain ordinary recomposition above.
                if len(projection.groups) != 1:
                    await self.recompose()
                    return
                await self._reconcile_keys(self, part.bindings)
            if not self.is_attached or self._closing or self._pruning:
                return
        if projection.palette is not None:
            self._update_key(
                self.query_one(".-command-palette", FooterKey),
                projection.palette,
                palette=True,
            )
        self.styles.grid_size_columns = projection.columns
        self._binding_projection = projection

    def _update_key(
        self, key: FooterKey, item: FooterBinding, *,
        grouped: bool = False, palette: bool = False,
    ) -> None:
        binding = item.binding
        description = "" if grouped else binding.description
        tooltip = (
            (binding.tooltip or binding.description) if palette else
            (item.tooltip or binding.description) if grouped else item.tooltip
        ) or None
        if (key.key, key.action, key.key_display, key.description, key._disabled, key.tooltip) == (
            binding.key, binding.action, item.key_display, description, not item.enabled, tooltip
        ):
            return
        changed_size = (key.key_display, key.description) != (item.key_display, description)
        key.key, key.action = binding.key, binding.action
        key.key_display, key.description = item.key_display, description
        key._disabled = not item.enabled
        key.set_class(not item.enabled, "-disabled")
        key.tooltip = tooltip
        key.refresh(layout=changed_size)

    async def _reconcile_keys(
        self, parent: Widget, items: tuple[FooterBinding, ...], *, grouped: bool = False
    ) -> None:
        existing = {
            key.action: key for key in parent.children
            if isinstance(key, FooterKey) and not key.has_class("-command-palette")
        }
        desired = {item.binding.action for item in items}
        removed = [key for action, key in existing.items() if action not in desired]
        if removed:
            await parent.remove_children(removed)
        if not parent.is_attached or self._closing or self._pruning:
            return
        ordered = []
        added = []
        for item in items:
            key = existing.get(item.binding.action)
            if key is None:
                key = self._make_key(item, grouped=grouped)
                added.append(key)
            else:
                self._update_key(key, item, grouped=grouped)
            ordered.append(key)
        if added:
            await parent.mount_all(added)
        if not parent.is_attached or self._closing or self._pruning:
            return
        ordered.extend(child for child in parent.children if child not in ordered)
        if list(parent.children) != ordered:
            positions = {child: index for index, child in enumerate(ordered)}
            parent.sort_children(key=positions.__getitem__)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self.allow_horizontal_scroll:
            self.release_anchor()
            if self._scroll_right_for_pointer(animate=True):
                event.stop()
                event.prevent_default()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.allow_horizontal_scroll:
            self.release_anchor()
            if self._scroll_left_for_pointer(animate=True):
                event.stop()
                event.prevent_default()

    def on_mount(self) -> None:
        self.screen.bindings_updated_signal.subscribe(self, self.bindings_changed)

    def on_unmount(self) -> None:
        self.screen.bindings_updated_signal.unsubscribe(self)
