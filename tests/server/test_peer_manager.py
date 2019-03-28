"""Test peer manager."""
import asyncio
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from snitun.exceptions import SniTunInvalidPeer
from snitun.server.peer import Peer
from snitun.server.peer_manager import PeerManager

from .const_fernet import FERNET_TOKENS, create_peer_config


def test_simple_init_peer_manager():
    """Simple init a peer manager."""
    manager = PeerManager(FERNET_TOKENS)

    assert manager._fernet
    assert not manager._peers
    assert manager._throttling is None


def test_init_new_peer():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.utcnow() + timedelta(days=1)
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


def test_init_new_peer_not_valid_time():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.utcnow() - timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    with pytest.raises(SniTunInvalidPeer):
        manager.create_peer(fernet_token)


def test_init_new_peer_invalid_fernet():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    with pytest.raises(SniTunInvalidPeer):
        manager.create_peer(os.urandom(100))


def test_init_new_peer_with_removing():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.utcnow() + timedelta(days=1)
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
    assert not hostname in manager._peers


def test_init_new_peer_throttling():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS, throttling=500)

    valid = datetime.utcnow() + timedelta(days=1)
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


def test_init_dual_peer_with_removing():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.utcnow() + timedelta(days=1)
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
    assert not hostname in manager._peers


async def test_init_dual_peer_with_multiplexer(multiplexer_client):
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.utcnow() + timedelta(days=1)
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
    assert not hostname in manager._peers
