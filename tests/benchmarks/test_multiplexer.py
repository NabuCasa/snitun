import asyncio
import ipaddress

import pytest
from pytest_codspeed import BenchmarkFixture

from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer

IP_ADDR = ipaddress.ip_address("8.8.8.8")


@pytest.mark.parametrize(
    ("size", "message_count"),
    [(2048, 1000), (1024 * 1024, 100)],
    ids=["1000@2KiB", "250@1MiB"],
)
def test_multiplex_channel_message(
    benchmark: BenchmarkFixture,
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    size: int,
    message_count: int,
) -> None:
    """Test writing 1000 2048 byte messages to the channel and reading them back."""
    assert not multiplexer_client._channels
    assert not multiplexer_server._channels
    loop = asyncio.get_event_loop()

    async def setup_channel() -> tuple[MultiplexerChannel, MultiplexerChannel]:
        channel_client = await multiplexer_client.create_channel(
            IP_ADDR,
            lambda _: None,
        )
        await asyncio.sleep(0.1)

        channel_server = multiplexer_server._channels.get(channel_client.id)

        assert channel_client
        assert channel_server

        return channel_client, channel_server

    payload = b"x" * size

    async def _async_read_write_messages(
        channel_client: MultiplexerChannel,
        channel_server: MultiplexerChannel,
    ) -> None:
        for _ in range(message_count):
            await channel_client.write(payload)
            await channel_server.read()

    channel_client, channel_server = loop.run_until_complete(setup_channel())

    @benchmark
    def read_write_channel() -> None:
        loop.run_until_complete(
            _async_read_write_messages(channel_client, channel_server),
        )
