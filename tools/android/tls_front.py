"""Terminate TLS on localhost:LISTEN and forward the bytes to 127.0.0.1:TARGET.

    python tools/android/tls_front.py CERT KEY LISTEN TARGET

The Qt client speaks to a bus only over HTTPS (`HttpsMcpEndpoint`), and a connector serves
plain HTTP on loopback behind tailscale's TLS. A scratch bus's connector has no tailscale in
front, so this stands in for it: a self-signed certificate the client is told to trust
(`SSL_CERT_FILE`), in front of the connector's loopback port. Prints `ready` once listening.
"""

import asyncio
import ssl
import sys


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


async def main(cert: str, key: str, listen: int, target: int) -> None:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert, key)

    async def accepted(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", target)
        await asyncio.gather(pipe(client_reader, upstream_writer), pipe(upstream_reader, client_writer))

    server = await asyncio.start_server(accepted, "127.0.0.1", listen, ssl=context)
    print("ready", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])))
