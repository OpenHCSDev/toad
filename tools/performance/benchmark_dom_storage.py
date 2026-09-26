"""Instrumented construction/retention fixture, not a terminal frame benchmark."""

import gc
import json
import time
import tracemalloc

from textual.dom import DOMNode

tracemalloc.start()
baseline = tracemalloc.get_traced_memory()[0]
start = time.perf_counter()
nodes = [DOMNode(classes="component") for _ in range(3000)]
elapsed = (time.perf_counter() - start) * 1000
retained = tracemalloc.get_traced_memory()[0] - baseline
print(json.dumps({"nodes": len(nodes), "construction_ms_with_tracemalloc": round(elapsed, 2),
                  "retained_bytes": retained, "gc_enabled": gc.isenabled(),
                  "eager_tree_collections": sum("_nodes" in node.__dict__ for node in nodes),
                  "eager_query_caches": sum("_query_one_cache" in node.__dict__ for node in nodes)}))
