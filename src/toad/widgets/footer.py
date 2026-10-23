from textual.widgets import Footer
from ui_theme.scheme import FooterToneColour
from toad.tone_paint import TonePaint
from toad.setting_widget import SettingVisibility


class ToadFooter(SettingVisibility, TonePaint, Footer, setting="ui.footer"):
    tone = FooterToneColour
