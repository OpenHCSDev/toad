"""Column geometry shared by every viewed document."""
from textual.containers import ScrollableContainer
from toad.settings_scope import SettingsReader


class ColumnLayout(SettingsReader):
    def apply_column_layout(self):
        ui = self.settings.ui
        self.styles.max_width = max(10, ui.column_width) if ui.column else None
        for reader in self.walk_children(ScrollableContainer):
            reader.styles.scrollbar_size_vertical = ui.scrollbar.size
