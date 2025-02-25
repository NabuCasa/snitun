
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.message import MultiplexerMessage,CHANNEL_FLOW_DATA
import ipaddress
import asyncio
from ..conftest import Client
from pytest_codspeed import BenchmarkFixture
IP_ADDR = ipaddress.ip_address("8.8.8.8")


def test_process_1000_channel_messages(
    benchmark: BenchmarkFixture,
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test writing 1000 messages to the channel and reading them back."""
    assert not multiplexer_client._channels
    assert not multiplexer_server._channels
    loop = asyncio.get_event_loop()

    async def setup_channel() -> tuple[MultiplexerChannel, MultiplexerChannel]:
        channel_client = await multiplexer_client.create_channel(IP_ADDR, lambda _: None)
        await asyncio.sleep(0.1)

        channel_server = multiplexer_server._channels.get(channel_client.id)

        assert channel_client
        assert channel_server

        return channel_client, channel_server


    large_payload = b"x" * 1024 * 1024
    async def _async_read_write_messages(channel_client: MultiplexerChannel, channel_server:MultiplexerChannel) -> None:
        for _ in range(1000):
            await channel_client.write(large_payload)
            await channel_server.read()


    channel_client, channel_server = loop.run_until_complete(setup_channel())

    @benchmark
    def read_write_channel() -> None:
        loop.run_until_complete(_async_read_write_messages(channel_client, channel_server))
