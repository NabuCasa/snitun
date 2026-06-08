"""Test trustme configuration is valid."""

import asyncio
import socket
import ssl


def get_unused_port_socket(
    host: str,
    family: socket.AddressFamily = socket.AF_INET,
) -> socket.socket:
    return get_port_socket(host, 0, family)


def get_port_socket(
    host: str,
    port: int,
    family: socket.AddressFamily = socket.AF_INET,
) -> socket.socket:
    s = socket.socket(family, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    return s


async def test_tls_loopback(
    client_ssl_context: ssl.SSLContext,
    server_ssl_context: ssl.SSLContext,
) -> None:
    """Test a loopback with TLS.

    This is a sanity check to make sure our trustme setup is working.
    """
    server_sock = get_unused_port_socket("127.0.0.1")

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle client."""
        writer.write(b"SERVER\n")
        await writer.drain()
        await reader.readline()
        writer.close()

    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w),
        ssl=server_ssl_context,
        sock=server_sock,
    )
    await server.start_serving()
    target_port = server_sock.getsockname()[1]
    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        target_port,
        ssl=client_ssl_context,
    )
    writer.write(b"CLIENT\n")
    await writer.drain()
    assert await reader.readline() == b"SERVER\n"
    writer.close()
    server.close()
    await server.wait_closed()
