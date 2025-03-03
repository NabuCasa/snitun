import asyncio

import pytest
from pytest_codspeed import BenchmarkFixture

from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer

from ..conftest import Client
from ..server.const_tls import TLS_1_2


@pytest.mark.parametrize(
    ("message_size", "count"),
    [(8192, 1000), (1024 * 1024, 50)],
    ids=["1000@8KiB", "25@1MiB"],
)
def test_server_send_message(
    benchmark: BenchmarkFixture,
    multiplexer_client: Multiplexer,
    test_client_ssl: Client,
    message_size: int,
    count: int,
) -> None:
    """Test writing messages to the channel and reading them back."""
    loop = asyncio.get_event_loop()

    async def setup() -> MultiplexerChannel:
        test_client_ssl.writer.write(TLS_1_2)
        await test_client_ssl.writer.drain()
        await asyncio.sleep(0.1)

        assert multiplexer_client._channels
        channel = next(iter(multiplexer_client._channels.values()))

        client_hello = await channel.read()
        assert client_hello == TLS_1_2
        return channel

    channel = loop.run_until_complete(setup())

    message = b"x" * message_size

    async def round_trip_messages():
        for _ in range(count):
            test_client_ssl.writer.write(message)
            received = 0
            while received != message_size:
                received += len(await channel.read())

    @benchmark
    def read_write_channel() -> None:
        loop.run_until_complete(round_trip_messages())

    async def teardown():
        channel.close()

    loop.run_until_complete(teardown())
