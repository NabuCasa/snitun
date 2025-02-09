
from snitun.multiplexer.message import MultiplexerChannelId

def test_multiplexer_channel_id() -> None:
    """Test MultiplexerChannelId."""
    channel_id = MultiplexerChannelId(b"testtesttesttest")
    assert channel_id.bytes == b"testtesttesttest"
    assert channel_id.hex == "74657374746573747465737474657374"
    assert str(channel_id) == "74657374746573747465737474657374"
