"""Native theme choices derive from Textual's authoritative declarations."""

from agent_comms.declared_family import DeclaredFamily
from textual.theme import BUILTIN_THEMES

from toad.setting_choices import Choice


class ThemeChoice(Choice, DeclaredFamily, affix="Theme"):
    """Members derive from Textual's authoritative theme declarations."""

    @classmethod
    def label(cls) -> str:
        return cls.theme.name


for _name, _theme in BUILTIN_THEMES.items():
    type(ThemeChoice)(
        "".join(part.title() for part in _name.split("-")) + "Theme",
        (ThemeChoice,),
        {"theme": _theme, "__module__": __name__},
        declared_name=_name,
    )
del _name, _theme
