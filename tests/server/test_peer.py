"""Test a Peer object."""
import asyncio
import hashlib
import os

import pytest

from snitun.multiplexer.message import CHANNEL_FLOW_PING
from snitun.multiplexer.crypto import CryptoTransport
from snitun.server.peer import Peer
from snitun.exceptions import SniTunChallengeError


def test_init_peer():
    """Test simple init of peer."""
    peer = Peer("localhost", [], os.urandom(32), os.urandom(16))

    assert peer.hostname == "localhost"
    assert peer.multiplexer is None
    assert peer.policy_connection_whitelist("8.8.8.8")


def test_init_peer_policy():
    """Test simple init of peer."""
    peer_strict = Peer("localhost", ["8.8.1.1"], os.urandom(32), os.urandom(16))
    peer_no_strict = Peer("localhost", [], os.urandom(32), os.urandom(16))

    assert peer_no_strict.policy_connection_whitelist("8.8.8.8")
    assert not peer_strict.policy_connection_whitelist("8.8.8.8")
    assert peer_strict.policy_connection_whitelist("8.8.1.1")


async def test_init_peer_multiplexer(loop, test_client, test_server):
    """Test setup multiplexer."""
    client = test_server[0]
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)

    peer = Peer("localhost", [], aes_key, aes_iv)
    crypto = CryptoTransport(aes_key, aes_iv)

    with pytest.raises(RuntimeError):
        await peer.wait_disconnect()

    init_task = loop.create_task(
        peer.init_multiplexer_challenge(test_client.reader, test_client.writer))
    await asyncio.sleep(0.1)

    assert not init_task.done()
    assert not peer.is_ready

    token = await client.reader.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    client.writer.write(crypto.encrypt(token))
    await client.writer.drain()
    await asyncio.sleep(0.1)

    assert init_task.exception() is None
    assert init_task.done()
    assert peer.is_ready
    assert not peer.multiplexer.wait().done()

    client.writer.close()
    client.close.set()

    await asyncio.sleep(0.1)
    assert peer.multiplexer.wait().done()


async def test_init_peer_multiplexer_crypto(loop, test_client, test_server):
    """Test setup multiplexer with crypto."""
    client = test_server[0]
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)

    peer = Peer("localhost", [], aes_key, aes_iv)
    crypto = CryptoTransport(aes_key, aes_iv)

    with pytest.raises(RuntimeError):
        await peer.wait_disconnect()

    init_task = loop.create_task(
        peer.init_multiplexer_challenge(test_client.reader, test_client.writer))
    await asyncio.sleep(0.1)

    assert not init_task.done()
    assert not peer.is_ready

    token = await client.reader.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    client.writer.write(crypto.encrypt(token))
    await client.writer.drain()
    await asyncio.sleep(0.1)

    assert init_task.exception() is None
    assert init_task.done()
    assert peer.is_ready
    assert not peer.multiplexer.wait().done()

    peer.multiplexer.ping()
    await asyncio.sleep(0.1)

    ping_data = await client.reader.read(1024)
    ping = crypto.decrypt(ping_data)

    assert ping[16] == CHANNEL_FLOW_PING
    assert int.from_bytes(ping[17:21], 'big') == 0

    client.writer.close()
    client.close.set()

    await asyncio.sleep(0.1)
    assert peer.multiplexer.wait().done()


async def test_init_peer_wrong_challenge(loop, test_client, test_server):
    """Test setup multiplexer wrong challenge."""
    client = test_server[0]
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)

    peer = Peer("localhost", [], aes_key, aes_iv)
    crypto = CryptoTransport(aes_key, aes_iv)

    with pytest.raises(RuntimeError):
        await peer.wait_disconnect()

    init_task = loop.create_task(
        peer.init_multiplexer_challenge(test_client.reader, test_client.writer))
    await asyncio.sleep(0.1)

    assert not init_task.done()

    token = await client.reader.readexactly(32)
    client.writer.write(crypto.encrypt(token))
    await client.writer.drain()
    await asyncio.sleep(0.1)

    with pytest.raises(SniTunChallengeError):
        raise init_task.exception()
    assert init_task.done()

    client.writer.close()
    client.close.set()
