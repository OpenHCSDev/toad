"""Read-only native widget cohorts; counts do not claim transitive heap ownership."""

from collections import Counter, defaultdict
import sys

from textual.screen import Screen
from textual.widget import Widget

from toad.widgets.side_bar import SideBar
from toad.widgets.transcript_history import TranscriptFragmentView


def widget_cohorts(objects, app, *, limit=60):
    active = app.screen
    backdrops = set(app._background_screens)
    cohorts = defaultdict(Counter)
    totals = defaultdict(Counter)
    for widget in objects:
        if not isinstance(widget, Widget):
            continue
        node = widget
        subtree = "chrome_or_other"
        owner = None
        while isinstance(node, Widget):
            if isinstance(node, TranscriptFragmentView):
                subtree = "transcript_fragment"
            elif isinstance(node, SideBar):
                subtree = "sidebar"
            if isinstance(node, Screen):
                owner = node
                break
            node = node._parent
        visibility = ("active" if owner is active else "backdrop" if owner in backdrops
                      else "inactive" if owner is not None else "unowned")
        lifecycle = "closed" if widget._closed else "closing" if widget._closing else "live"
        task = widget._task
        values = {
            "widgets": 1,
            "live_message_pumps": int(task is not None and not task.done()),
            "shallow_instance_dict_bytes": sys.getsizeof(widget.__dict__),
        }
        cohorts[visibility, lifecycle, subtree, type(widget).__name__].update(values)
        totals[visibility, lifecycle, subtree].update(values)
    return {
        "totals": [{"visibility": visibility, "lifecycle": lifecycle, "subtree": subtree, **counts}
                   for (visibility, lifecycle, subtree), counts in sorted(totals.items())],
        "classes": [{"visibility": visibility, "lifecycle": lifecycle, "subtree": subtree,
                     "widget_class": name, **counts}
                    for (visibility, lifecycle, subtree, name), counts in sorted(
                        cohorts.items(), key=lambda item: -item[1]["widgets"])[:limit]],
    }
