"""Test peer manager."""
from datetime import datetime, timedelta
import os

import pytest

from snitun.server.peer import Peer
from snitun.server.peer_manager import PeerManager
from snitun.exceptions import SniTunInvalidPeer

from .const_fernet import FERNET_TOKENS, create_peer_config


def test_simple_init_peer_manager():
    """Simple init a peer manager."""
    manager = PeerManager(FERNET_TOKENS)

    assert manager._fernet
    assert not manager._peers


def test_init_new_peer():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    whitelist = []
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, whitelist,
                                      aes_key, aes_iv)

    peer = manager.register_peer(fernet_token)
    assert peer.hostname == hostname
    assert peer._whitelist == whitelist
    assert not peer.is_ready

    assert manager.get_peer(hostname)
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers


def test_init_new_peer_whitelist():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    whitelist = ["8.8.8.8"]
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, whitelist,
                                      aes_key, aes_iv)

    peer = manager.register_peer(fernet_token)
    assert peer.hostname == hostname
    assert peer._whitelist == whitelist
    assert not peer.is_ready

    assert manager.get_peer(hostname)
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers

    assert peer.policy_connection_whitelist("8.8.8.8")
    assert not peer.policy_connection_whitelist("8.8.1.1")


def test_init_new_peer_not_valid_time():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.utcnow() - timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    whitelist = ["8.8.8.8"]
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, whitelist,
                                      aes_key, aes_iv)

    with pytest.raises(SniTunInvalidPeer):
        manager.register_peer(fernet_token)


def test_init_new_peer_invalid_fernet():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    with pytest.raises(SniTunInvalidPeer):
        manager.register_peer(os.urandom(100))


def test_init_new_peer_with_removing():
    """Init a new peer."""
    manager = PeerManager(FERNET_TOKENS)

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    whitelist = []
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, whitelist,
                                      aes_key, aes_iv)

    peer = manager.register_peer(fernet_token)
    assert peer.hostname == hostname
    assert peer._whitelist == whitelist
    assert not peer.is_ready

    assert manager.get_peer(hostname)
    assert not manager.peer_available(hostname)
    assert hostname in manager._peers

    manager.remove_peer(peer)
    assert manager.get_peer(hostname) is None
    assert not manager.peer_available(hostname)
    assert not hostname in manager._peers
