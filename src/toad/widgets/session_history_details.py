"""Saved transcript availability and bus-input proof have separate owners."""


class SessionHistoryDetails:
    def __init__(self, read_history, native):
        self.read_history = read_history
        self.native = native

    @property
    def summary(self):
        parts = []
        if self.read_history is not None:
            history = self.read_history()
            parts.append("Saved history available" if history is not None and history.state.reports_coverage
                         else "Saved history not loaded")
        if self.attention:
            parts.append("Bus input verification unavailable")
        return parts

    @property
    def attention(self):
        return self.native is not None and self.native.status == "unavailable"

    def overview(self, activity):
        return "\n\n".join([
            *self.summary,
            *(str(item.render()) for item in (activity, self.native)
              if item is not None and item.display),
        ])
