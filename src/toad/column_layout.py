"""Column geometry shared by every viewed document."""
from textual.containers import ScrollableContainer
from toad.client.view_layout import ConversationColumn
from toad.settings_scope import SettingsReader


class ColumnLayout(ConversationColumn, SettingsReader):
    def apply_column_layout(self):
        ui = self.settings.ui
        self.styles.max_width = self.column_cells(ui)
        for reader in self.walk_children(ScrollableContainer):
            reader.styles.scrollbar_size_vertical = self.scrollbar_cells(ui)
