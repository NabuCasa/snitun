"""Tests for peer listener & manager."""
import asyncio
from datetime import datetime, timedelta
import hashlib
import os

from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.crypto import CryptoTransport
from snitun.server.listener_peer import PeerListener

from .const_fernet import create_peer_config
from .const_tls import TLS_1_2


async def test_server_full(peer_manager, peer_listener, test_client_peer,
                           sni_proxy, test_client_ssl):
    """Run a full flow of with a peer after that disconnect."""
    peer_messages = []
    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    whitelist = []
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, whitelist,
                                      aes_key, aes_iv)

    crypto = CryptoTransport(aes_key, aes_iv)

    test_client_peer.writer.write(fernet_token)
    await test_client_peer.writer.drain()

    token = await test_client_peer.reader.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    test_client_peer.writer.write(crypto.encrypt(token))

    await test_client_peer.writer.drain()
    await asyncio.sleep(0.1)

    assert peer_manager.peer_available(hostname)

    async def mock_new_channel(channel):
        """Mock new channel."""
        while True:
            message = await channel.read()
            peer_messages.append(message)

    multiplexer = Multiplexer(crypto, test_client_peer.reader,
                              test_client_peer.writer, mock_new_channel)

    test_client_ssl.writer.write(TLS_1_2)
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    assert peer_messages
    assert peer_messages[0] == TLS_1_2

    await multiplexer.shutdown()
    await multiplexer.wait()
    await asyncio.sleep(0.1)

    assert not peer_manager.peer_available(hostname)
