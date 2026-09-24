"""Explicit entry point for a persistent, data-only renderer endpoint."""

import argparse
from pathlib import Path

def main() -> None:
    # Spawn workers re-import this entry module. Only the service process owns
    # ZMQ and its lifecycle imports; CPU children load their typed task modules.
    from zmqruntime.runner import serve_forever

    from toad.render_service import RenderServiceConfig
    from toad.render_zmq import RendererEndpoint, RendererServer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--port", type=int, default=19001)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--pending", type=int, default=4)
    parser.add_argument("--client-lease", type=float, default=60.0)
    arguments = parser.parse_args()
    endpoint = RendererEndpoint(arguments.directory, arguments.version, arguments.port)
    server = RendererServer(endpoint, RenderServiceConfig(
        arguments.workers, arguments.pending, arguments.client_lease,
    ))
    serve_forever(server, poll_interval=.001, on_shutdown=server.service.close)


if __name__ == "__main__":
    main()
