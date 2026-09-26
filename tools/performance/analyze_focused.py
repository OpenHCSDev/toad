"""Bounded Python allocation-stack and CPU-profile summaries."""

from collections import Counter
import json
from pathlib import Path
import pstats
import sys


def location(frame):
    name, path, line = frame
    return f"{Path(path).name}:{line}:{name}"


path = Path(sys.argv[1])
if path.suffix == ".pstats":
    stats = pstats.Stats(str(path))
    stats.strip_dirs().sort_stats("cumulative").print_stats(45)
    stats.sort_stats("tottime").print_stats(30)
    stats.print_callers("_parent", "screen", "_check_refresh", "_refresh_layout", "toggle")
else:
    import memray
    reader = memray.FileReader(str(path))
    print(reader.metadata)
    for title, records in (
        ("peak", reader.get_high_watermark_allocation_records()),
        ("still_allocated_at_end", reader.get_leaked_allocation_records()),
    ):
        own, inclusive, counts = Counter(), Counter(), Counter()
        total = 0
        for record in records:
            stack = record.stack_trace()
            total += record.size
            if not stack:
                continue
            key = location(stack[0])
            own[key] += record.size
            counts[key] += record.n_allocations
            for key in {location(frame) for frame in stack}:
                inclusive[key] += record.size
        print(json.dumps({"scope": title, "bytes": total,
                          "top_own": own.most_common(25), "top_inclusive": inclusive.most_common(30),
                          "top_counts": counts.most_common(20)}, indent=2))
