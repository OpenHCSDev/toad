"""Inspect locally captured, trusted DTO bundles; omit message contents."""

from collections import Counter
from pathlib import Path
import pickle
import sys

path = Path(sys.argv[1])
with path.open("rb") as source:
    state = pickle.load(source)
assert state["schema"] == 1
print("payload keys:", sorted(state))
print("screen types:", Counter(view["screen_class"] for view in state["views"]))
print("sidebar snapshot:", type(state.get("sidebar_snapshot")).__name__)
print("view summaries:", [{"mode": view["mode"],
    "pages": sum(len(pager["pages"]) for pager in view["history_pages"]),
    "events": sum(len(page.events) for pager in view["history_pages"] for page, _, _ in pager["pages"]),
    "native_pagers": sum(bool(pager["through"].session_file) for pager in view["history_pages"] if pager.get("through") is not None),
    "draft_line_counts": [len(draft["lines"]) if draft["lines"] is not None else None for draft in view["drafts"]],
    "direct_blocks": sum(block["parent_class"] == "Contents" for block in view["live_blocks"]),
    "wire_messages": len(view.get("wire_history", ())), "drafts": len(view["drafts"])}
    for view in state["views"]])
