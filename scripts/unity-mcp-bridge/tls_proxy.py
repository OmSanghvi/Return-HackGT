"""Minimal TLS-terminating TCP proxy for the NemoClaw -> Unity MCP bridge.

Terminates HTTPS on --listen-host:--listen-port with a certificate chain signed
by this machine's private CA, and forwards the decrypted byte stream verbatim
to mcp-proxy on 127.0.0.1:--backend-port. It never parses HTTP, so it carries
MCP Streamable HTTP (POST + SSE) unchanged.

It exists because mcp-proxy's CLI can't serve TLS, and NemoClaw's `mcp add`
requires an https:// URL whose certificate chains to a CA the sandbox trusts.

Bind only to the Windows side of the WSL virtual switch, never 0.0.0.0: that
would expose the Unity Editor to the LAN.
"""

import argparse
import asyncio
import ssl


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        writer.close()


def make_handler(backend_host: str, backend_port: int):
    async def handle_client(client_reader, client_writer) -> None:
        try:
            backend_reader, backend_writer = await asyncio.open_connection(backend_host, backend_port)
        except OSError as exc:
            print(f"Failed to connect to backend: {exc}", flush=True)
            client_writer.close()
            return
        await asyncio.gather(
            pipe(client_reader, backend_writer),
            pipe(backend_reader, client_writer),
        )

    return handle_client


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listen-host", required=True)
    parser.add_argument("--listen-port", type=int, default=9443)
    parser.add_argument("--backend-host", default="127.0.0.1")
    parser.add_argument("--backend-port", type=int, default=19443)
    parser.add_argument("--cert", required=True, help="PEM leaf + CA chain")
    parser.add_argument("--key", required=True, help="PEM leaf private key")
    args = parser.parse_args()

    if args.listen_host in ("0.0.0.0", "::", ""):
        parser.error("refusing to bind all interfaces; pass the WSL-facing address")

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(args.cert, args.key)
    server = await asyncio.start_server(
        make_handler(args.backend_host, args.backend_port),
        args.listen_host,
        args.listen_port,
        ssl=ssl_context,
    )
    addr = server.sockets[0].getsockname()
    print(
        f"TLS proxy listening on https://{addr[0]}:{addr[1]} -> "
        f"http://{args.backend_host}:{args.backend_port}",
        flush=True,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
