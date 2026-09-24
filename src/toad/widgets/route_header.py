"""One compact, linked header for incoming and outgoing routed messages."""

from agent_comms import MessageRoute
from textual.content import Content
from textual.style import Style
from textual.widgets import Static
from textual import events

from toad.widgets.comms_sidebar import SelectTarget
from toad.pill import pill


class RouteHeader(Static, can_focus=True):
    DEFAULT_CSS = """
    RouteHeader {
        width: 1fr; height: auto; margin: 0; padding: 0 1;
        color: $text-muted; background: transparent;
    }
    RouteHeader:hover, RouteHeader:focus { text-style: underline; }
    """
    BINDINGS = [("enter", "open_primary", "Open thread"),
                ("shift+enter", "open_destination", "Open destination")]

    def __init__(self, route: MessageRoute, *, incoming: bool = False) -> None:
        self.route = route
        self.incoming = incoming
        if incoming:
            content = Content.styled("↙ ", "$accent") + pill("FROM", "$accent", "$accent", filled=False)
            content += Content(" ") + self.link(route.sender) + Content.styled(" · ", "$text-muted")
            content += (self.link(route.targets[0]) if route.targets and route.targets[0].startswith("#")
                        else Content(route.incoming_scope))
        else:
            content = Content.styled("↗ ", "$accent") + pill("TO", "$accent", "$accent", filled=False) + Content(" ")
            for index, target in enumerate(route.targets):
                if index:
                    content += Content(", ")
                content += self.link(target)
        super().__init__(content, markup=False)

    @staticmethod
    def link(target: str) -> Content:
        return Content.styled(target, "$text-accent bold underline").stylize(
            Style.from_meta({"@click": ("open_target", (target,))})
        )

    def action_open_target(self, target: str) -> None:
        self.post_message(SelectTarget(target, "channel" if target.startswith("#") else "thread"))

    def action_open_primary(self) -> None:
        if self.incoming:
            self.action_open_target(self.route.sender)
        else:
            self.action_open_destination()

    def action_open_destination(self) -> None:
        if self.route.targets:
            self.action_open_target(self.route.targets[0])

    def on_click(self, event: events.Click) -> None:
        if event.button == 1 and not event.style.meta.get("@click"):
            event.stop()
            self.action_open_primary()
