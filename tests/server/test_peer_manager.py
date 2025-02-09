"""Test peer manager."""

import asyncio
from datetime import UTC, datetime, timedelta
import os

import pytest

from snitun.exceptions import SniTunInvalidPeer
from snitun.multiplexer.core import Multiplexer
from snitun.server.peer import Peer
from snitun.server.peer_manager import PeerManager, PeerManagerEvent

from .const_fernet import FERNET_TOKENS, create_peer_config


async def test_simple_init_peer_manager() -> None:
    """Simple init a peer manager."""
    manager = PeerManager(FERNET_TOKENS)

    assert manager._fernet
    assert not manager._peers
    assert manager._throttling is None


async def test_init_new_peer() -> None:
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    peer = manager.create_peer(fernet_token)
    assert peer.hostname == hostname
    assert not peer.is_ready
    assert not manager.get_peer(hostname)
    assert not manager.peer_available(hostname)
    assert hostname not in manager._peers
    assert manager.connections == 0

    manager.add_peer(peer)
    assert manager.get_peer(hostname)
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1


async def test_init_new_peer_with_alias() -> None:
    """Init a new peer with custom domain."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    alias = "localhost.custom"
    fernet_token = create_peer_config(
        valid.timestamp(),
        hostname,
        aes_key,
        aes_iv,
        alias=[alias],
    )

    peer = manager.create_peer(fernet_token)
    assert peer.hostname == hostname
    assert peer.alias == [alias]
    assert not peer.is_ready
    assert not manager.get_peer(hostname)
    assert not manager.get_peer(alias)
    assert not manager.peer_available(hostname)
    assert not manager.peer_available(alias)
    assert hostname not in manager._peers
    assert alias not in manager._peers
    assert manager.connections == 0

    manager.add_peer(peer)
    assert manager.get_peer(hostname)
    assert manager.get_peer(alias)
    assert not manager.peer_available(hostname)
    assert not manager.peer_available(alias)
    assert hostname in manager._peers
    assert alias in manager._peers
    assert manager.connections == 2


async def test_init_new_peer_not_valid_time() -> None:
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.now(tz=UTC) - timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    with pytest.raises(SniTunInvalidPeer):
        manager.create_peer(fernet_token)


async def test_init_new_peer_invalid_fernet() -> None:
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    with pytest.raises(SniTunInvalidPeer):
        manager.create_peer(os.urandom(100))


async def test_init_new_peer_with_removing() -> None:
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    peer = manager.create_peer(fernet_token)
    assert peer.hostname == hostname
    assert not peer.is_ready

    manager.add_peer(peer)
    assert manager.get_peer(hostname)
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1

    manager.remove_peer(peer)
    assert manager.get_peer(hostname) is None
    assert not manager.peer_available(hostname)
    assert hostname not in manager._peers


async def test_init_new_peer_with_events() -> None:
    """Init a new peer and remove with events."""
    events = []

    def _events(ev_peer: Peer, type_event: PeerManagerEvent) -> None:
        events.append((ev_peer, type_event))

    manager = PeerManager(FERNET_TOKENS, event_callback=_events)

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    peer = manager.create_peer(fernet_token)
    assert peer.hostname == hostname
    assert not peer.is_ready

    manager.add_peer(peer)
    assert manager.get_peer(hostname)
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1

    await asyncio.sleep(0.1)
    assert events[-1][0] == peer
    assert events[-1][1] == PeerManagerEvent.CONNECTED

    manager.remove_peer(peer)
    assert manager.get_peer(hostname) is None
    assert not manager.peer_available(hostname)
    assert hostname not in manager._peers

    await asyncio.sleep(0.1)
    assert events[-1][0] == peer
    assert events[-1][1] == PeerManagerEvent.DISCONNECTED


async def test_init_new_peer_throttling() -> None:
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS, throttling=500)

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    peer = manager.create_peer(fernet_token)
    assert peer.hostname == hostname
    assert not peer.is_ready
    assert peer._throttling == 500

    manager.add_peer(peer)
    assert manager.get_peer(hostname)
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1


async def test_init_dual_peer_with_removing() -> None:
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    peer1 = manager.create_peer(fernet_token)
    peer2 = manager.create_peer(fernet_token)
    assert peer1.hostname == hostname
    assert peer2.hostname == hostname
    assert not peer1.is_ready
    assert not peer2.is_ready

    manager.add_peer(peer1)
    assert manager.get_peer(hostname) == peer1
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1

    manager.add_peer(peer2)
    assert manager.get_peer(hostname) == peer2
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1

    manager.remove_peer(peer1)
    assert manager.get_peer(hostname) == peer2
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1

    manager.remove_peer(peer2)
    assert manager.get_peer(hostname) is None
    assert not manager.peer_available(hostname)
    assert hostname not in manager._peers


async def test_init_dual_peer_with_multiplexer(multiplexer_client: Multiplexer) -> None:
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    peer1 = manager.create_peer(fernet_token)
    peer2 = manager.create_peer(fernet_token)
    assert peer1.hostname == hostname
    assert peer2.hostname == hostname
    assert not peer1.is_ready
    assert not peer2.is_ready

    peer1._multiplexer = multiplexer_client
    assert peer1.is_ready

    manager.add_peer(peer1)
    assert manager.get_peer(hostname) == peer1
    assert manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1

    manager.add_peer(peer2)
    assert manager.get_peer(hostname) == peer2
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1

    manager.remove_peer(peer1)
    assert manager.get_peer(hostname) == peer2
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers
    assert manager.connections == 1

    await asyncio.sleep(0.1)
    assert not multiplexer_client.is_connected

    manager.remove_peer(peer2)
    assert manager.get_peer(hostname) is None
    assert not manager.peer_available(hostname)
    assert hostname not in manager._peers
