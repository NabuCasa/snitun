"""Tests for aiohttp snitun client."""
from unittest.mock import patch

from snitun.utils.aiohttp_client import SniTunClientAioHttp


async def test_init_client():
    """Init aiohttp client for test."""

    with patch("snitun.utils.aiohttp_client.SockSite"):
        client = SniTunClientAioHttp(None, None, "127.0.0.1")
