"""Tests for the server worker."""
from datetime import datetime, timedelta, timezone
import hashlib
import os
import socket
import time

from snitun.multiplexer.crypto import CryptoTransport
from snitun.server.worker import ServerWorker

from .const_fernet import FERNET_TOKENS, create_peer_config
from .const_tls import TLS_1_2


def test_worker_up_down(event_loop):
    """Test if worker start and stop."""
    worker = ServerWorker(FERNET_TOKENS)

    worker.start()
    assert worker.is_alive()
    assert worker.peer_size == 0
    worker.shutdown()

    assert worker.exitcode == 0
    assert not worker.is_alive()


def test_peer_connection(test_server_sync, test_client_sync, event_loop):
    """Run a full flow of with a peer."""
    worker = ServerWorker(FERNET_TOKENS)
    valid = datetime.now(tz=timezone.utc) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    worker.start()
    crypto = CryptoTransport(aes_key, aes_iv)

    worker.handover_connection(test_server_sync[-1], fernet_token, None)

    token = test_client_sync.recv(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    test_client_sync.sendall(crypto.encrypt(token))

    time.sleep(1)
    assert worker.is_responsible_peer(hostname)
    assert worker.peer_size == 1

    worker.shutdown()


def test_peer_connection_disconnect(test_server_sync, test_client_sync, event_loop):
    """Run a full flow of with a peer & disconnect."""
    worker = ServerWorker(FERNET_TOKENS)
    valid = datetime.now(tz=timezone.utc) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    worker.start()
    crypto = CryptoTransport(aes_key, aes_iv)

    worker.handover_connection(test_server_sync[-1], fernet_token, None)

    token = test_client_sync.recv(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    test_client_sync.sendall(crypto.encrypt(token))

    time.sleep(1)
    assert worker.is_responsible_peer(hostname)
    assert worker.peer_size == 1

    test_client_sync.shutdown(socket.SHUT_RDWR)
    time.sleep(1)
    assert not worker.is_responsible_peer(hostname)
    assert worker.peer_size == 0

    worker.shutdown()


def test_sni_connection(
    test_server_sync, test_client_sync, test_client_ssl_sync, event_loop
):
    """Run a full flow of with a peer."""
    worker = ServerWorker(FERNET_TOKENS)
    valid = datetime.now(tz=timezone.utc) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    alias = ["localhost.custom"]
    fernet_token = create_peer_config(
        valid.timestamp(), hostname, aes_key, aes_iv, alias=alias
    )

    worker.start()
    crypto = CryptoTransport(aes_key, aes_iv)

    worker.handover_connection(test_server_sync[0], fernet_token, None)

    token = test_client_sync.recv(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    test_client_sync.sendall(crypto.encrypt(token))

    time.sleep(1)
    assert worker.is_responsible_peer(hostname)
    for entry in alias:
        assert worker.is_responsible_peer(entry)

    worker.handover_connection(test_server_sync[1], TLS_1_2, hostname)
    assert len(test_client_sync.recv(1048)) == 32

    worker.shutdown()
