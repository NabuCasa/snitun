"""Tests for the server worker."""
import asyncio
from datetime import datetime, timedelta
import hashlib
import os
import time

from snitun.multiplexer.crypto import CryptoTransport
from snitun.server.worker import ServerWorker

from .const_fernet import FERNET_TOKENS, create_peer_config


def test_worker_up_down(loop):
    """Test if worker start and stop."""
    worker = ServerWorker(FERNET_TOKENS)

    worker.start()
    assert worker.is_alive()
    worker.shutdown()

    assert worker.exitcode == 0
    assert not worker.is_alive()


def test_peer_connection(test_server_sync, test_client_sync, loop):
    """Run a full flow of with a peer."""
    worker = ServerWorker(FERNET_TOKENS)
    valid = datetime.utcnow() + timedelta(days=1)
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

    worker.shutdown()