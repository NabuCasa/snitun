"""Test server utils."""

import asyncio
from datetime import timedelta
import os

import pytest

from snitun.client.client_peer import ClientPeer
from snitun.client.connector import EndpointConnector
from snitun.exceptions import SniTunConnectionError
from snitun.multiplexer.crypto import CIPHER_GCM
from snitun.server.listener_peer import PeerListener
from snitun.server.peer_manager import PeerManager
from snitun.utils import server

from ..server.const_fernet import FERNET_TOKENS


async def test_fernet_token(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
) -> None:
    """Test fernet token created by server."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = EndpointConnector("127.0.0.1", "8822")

    assert not peer_manager.peer_available("localhost")

    valid = timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = server.generate_client_token(
        FERNET_TOKENS,
        valid,
        hostname,
        aes_key,
        aes_iv,
    )

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")

    await client.stop()
    await asyncio.sleep(0.1)
    assert not peer_manager.peer_available("localhost")


async def test_fernet_token_gcm(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
) -> None:
    """An AES-GCM token connects end-to-end (handshake + multiplexer)."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = EndpointConnector("127.0.0.1", "8822")

    assert not peer_manager.peer_available("localhost")

    valid = timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    fernet_token = server.generate_client_token(
        FERNET_TOKENS,
        valid,
        "localhost",
        aes_key,
        aes_iv,
        cipher=CIPHER_GCM,
    )

    await client.start(connector, fernet_token, aes_key, aes_iv, cipher=CIPHER_GCM)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")

    await client.stop()
    await asyncio.sleep(0.1)
    assert not peer_manager.peer_available("localhost")


async def test_fernet_token_date(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
) -> None:
    """Test fernet token created by server as invalid."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = EndpointConnector("127.0.0.1", "8822")

    assert not peer_manager.peer_available("localhost")

    valid = timedelta(days=-1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = server.generate_client_token(
        FERNET_TOKENS,
        valid,
        hostname,
        aes_key,
        aes_iv,
    )

    with pytest.raises(SniTunConnectionError):
        await client.start(connector, fernet_token, aes_key, aes_iv)

    await asyncio.sleep(0.1)
    assert not peer_manager.peer_available("localhost")
