"""Test Client Peer connections."""

import asyncio
from datetime import UTC, datetime, timedelta
import ipaddress
import os

import pytest

from snitun.client.client_peer import ClientPeer
from snitun.client.connector import Connector
from snitun.exceptions import SniTunConnectionError
from snitun.server.listener_peer import PeerListener
from snitun.server.peer_manager import PeerManager

from ..server.const_fernet import create_peer_config

IP_ADDR = ipaddress.ip_address("8.8.8.8")


async def test_init_client_peer(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected
    assert client._multiplexer._throttling is None

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")


async def test_init_client_peer_with_alias(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test setup of ClientPeer with custom tomain."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")
    assert not peer_manager.peer_available("localhost.custom")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(
        valid.timestamp(),
        hostname,
        aes_key,
        aes_iv,
        alias=["localhost.custom"],
    )

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert peer_manager.peer_available("localhost.custom")
    assert client.is_connected
    assert client._multiplexer._throttling is None

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")
    assert not peer_manager.peer_available("localhost.custom")


async def test_init_client_peer_invalid_token(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=-1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    with pytest.raises(SniTunConnectionError):
        await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert not peer_manager.peer_available("localhost")


async def test_flow_client_peer(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test setup of ClientPeer, test flow."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")

    peer = peer_manager.get_peer("localhost")

    channel = await peer.multiplexer.create_channel(IP_ADDR, lambda _: None)
    await asyncio.sleep(0.1)

    assert channel.ip_address == IP_ADDR

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")


async def test_close_client_peer(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test setup of ClientPeer, test flow - close it."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")

    peer = peer_manager.get_peer("localhost")

    channel = await peer.multiplexer.create_channel(IP_ADDR, lambda _: None)
    await asyncio.sleep(0.1)

    assert channel.ip_address == IP_ADDR

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")


async def test_init_client_peer_wait(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected

    assert not client.wait().done()

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    with pytest.raises(RuntimeError):
        assert client.wait().done()


async def test_init_client_peer_wait_waits_for_task(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected

    assert not client.wait().done()

    # Shutdown the multiplexer from under the client
    client._multiplexer.shutdown()
    await client.wait()
    # Make sure the task is actually done
    assert client._handler_task.done()
    await client._stop_handler()
    # Make sure _stop_handler cleans up the task reference
    assert client._handler_task is None


async def test_client_peer_can_start_again(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test once the connection fails, we can start again."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected

    assert not client.wait().done()

    # Shutdown the multiplexer from under the client
    client._multiplexer.shutdown()
    await client.wait()
    assert not client.is_connected

    # Now make sure we can start again
    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")

    await client.stop()
    assert not client.is_connected


async def test_init_client_peer_throttling(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv, throttling=500)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected
    assert client._multiplexer._throttling == 0.002

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")


async def test_init_client_peer_stop_does_not_swallow_cancellation(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test stopping the peer does not swallow cancellation."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected

    task = asyncio.create_task(client._stop_handler())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")


async def test_init_client_peer_stop_twice(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test calling stop twice raises an error."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected

    await client.stop()
    with pytest.raises(RuntimeError):
        await client.stop()

    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")


async def test_init_client_peer_custom_protocol_version(
    peer_listener: PeerListener,
    peer_manager: PeerManager,
    connector: Connector,
) -> None:
    """Test setup of ClientPeer with custom protocol version."""
    client = ClientPeer("127.0.0.1", "8893")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    # Start with protocol version 0
    await client.start(connector, fernet_token, aes_key, aes_iv, protocol_version=0)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected

    # Verify the multiplexer was created with protocol version 0
    assert client._multiplexer._peer_protocol_version == 0

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")
