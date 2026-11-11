from collections.abc import Mapping
from itertools import chain
from typing import ClassVar

from textual.css.native import Keyword, NativeDeclaration, Number, Percent, TextVariable, Variable
from textual.css.styles import Styles
from textual.widgets import Footer
from textual.widgets._footer import FooterKey, FooterKeyComponent
from ui_theme.scheme import FooterBackgroundColour, FooterToneColour, ForegroundColour, MutedColour, SecondaryColour
from toad.native_style import TransparentBackground
from toad.tone_paint import TonePaint
from toad.setting_widget import SettingVisibility


type Components = Mapping[FooterKeyComponent, tuple[NativeDeclaration, ...]]

ANSI_REVERSE = (
    NativeDeclaration.of(Styles.color, Keyword("ansi_default")),
    NativeDeclaration.of(Styles.background, Keyword("ansi_default")),
    NativeDeclaration.of(Styles.text_style, Keyword("reverse")),
)


class ToadFooterKey(FooterKey):
    """A key's paint follows its footer's compactness, its own state and the theme."""

    native_components: ClassVar[Components] = {
        FooterKeyComponent.KEY: (
            NativeDeclaration.of(Styles.color, Variable(ForegroundColour.name)),
            NativeDeclaration.of(Styles.background, Variable(SecondaryColour.name), Percent(15)),
            NativeDeclaration.of(Styles.padding, Number(0), Number(1)),
        ),
        FooterKeyComponent.DESCRIPTION: (
            NativeDeclaration.of(Styles.color, TextVariable(MutedColour.name)),
            NativeDeclaration.of(Styles.background, Variable(FooterBackgroundColour.name)),
            NativeDeclaration.of(Styles.padding, Number(0), Number(1), Number(0), Number(0)),
        ),
    }
    compact_components: ClassVar[Components] = {
        FooterKeyComponent.KEY: (NativeDeclaration.of(Styles.padding, Number(0)),),
        FooterKeyComponent.DESCRIPTION: (
            NativeDeclaration.of(Styles.padding, Number(0), Number(0), Number(0), Number(1)),
        ),
    }
    disabled_components: ClassVar[Components] = {
        FooterKeyComponent.KEY: (NativeDeclaration.of(Styles.text_opacity, Percent(60)),),
    }
    ansi_components: ClassVar[Components] = {FooterKeyComponent.KEY: ANSI_REVERSE}
    ansi_hover_components: ClassVar[Components] = dict.fromkeys(FooterKeyComponent, ANSI_REVERSE)

    def native_component_declarations(self, component: FooterKeyComponent) -> tuple[NativeDeclaration, ...]:
        ink = self.app.colours.ink
        layers = (
            self.compact_components if self.query_ancestor(Footer).compact else {},
            self.disabled_components if self._disabled else {},
            ink.choose(true_colour={}, ansi=self.ansi_components),
            ink.choose(true_colour={}, ansi=self.ansi_hover_components) if self.mouse_hover else {},
        )
        return (
            *super().native_component_declarations(component),
            *chain.from_iterable(layer.get(component, ()) for layer in layers),
        )


class ToadFooter(
    SettingVisibility,
    TransparentBackground,
    TonePaint,
    Footer,
    setting='ui.footer',
):
    COMPOSITING_LAYER = True
    # The footer's tone shows through: no stylesheet paint over it.
    tone = FooterToneColour
    key_type = ToadFooterKey
