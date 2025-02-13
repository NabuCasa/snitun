"""Tests for aiohttp snitun client."""

from unittest.mock import AsyncMock

from aiohttp import web
import pytest
from pytest_aiohttp import AiohttpServer

from snitun.utils.aiohttp_client import SniTunClientAioHttp


async def test_init_client(aiohttp_server: AiohttpServer) -> None:
    """Init aiohttp client for test."""
    app = web.Application()
    server = await aiohttp_server(app)
    client = SniTunClientAioHttp(server.runner, None, "127.0.0.1")

    assert not client.is_connected


async def test_client_stop_no_wait(aiohttp_server: AiohttpServer) -> None:
    """Test that we do not wait if wait is not passed to the stop."""
    app = web.Application()
    server = await aiohttp_server(app)
    client = SniTunClientAioHttp(server.runner, None, "127.0.0.1")
    await client.stop()
    await client.stop(wait=True)
    assert not client.is_connected



async def test_endpoint_connection_error_callback_deprecated(aiohttp_server: AiohttpServer) -> None:
    """Test passing endpoint_connection_error_callback throws a warning."""
    app = web.Application()
    server = await aiohttp_server(app)
    client = SniTunClientAioHttp(server.runner, None, "127.0.0.1")
    with pytest.warns(DeprecationWarning, match=(

        r"Passing endpoint_connection_error_callback to SniTunClientAioHttp.start\(\)"
        r" is deprecated, is not longer used, and it will be removed in the future.")):
        await client.start(False, endpoint_connection_error_callback=AsyncMock())
    await client.stop(wait=True)
    assert not client.is_connected
