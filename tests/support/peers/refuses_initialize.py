"""Answers the first request with a JSON-RPC error, then stays connected."""

import json
import sys

if __name__ == "__main__":
    request = json.loads(sys.stdin.readline())
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                      "error": {"code": -32603, "message": "AGENT_REFUSED_TO_START"}}), flush=True)
    sys.stdin.read()
