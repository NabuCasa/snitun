from snitun.multiplexer.message import FlowType, MultiplexerChannelId


def test_multiplexer_channel_id() -> None:
    """Test MultiplexerChannelId."""
    channel_id = MultiplexerChannelId(b"testtesttesttest")
    assert channel_id.bytes == b"testtesttesttest"
    assert channel_id.hex == "74657374746573747465737474657374"
    assert str(channel_id) == "74657374746573747465737474657374"


def test_message_types() -> None:
    """Test FlowType."""
    assert FlowType.NEW == 0x01
    assert FlowType.NEW.value == 0x01
    assert FlowType.DATA == 0x02
    assert FlowType.DATA.value == 0x02
    assert FlowType.CLOSE == 0x04
    assert FlowType.CLOSE.value == 0x04
    assert FlowType.PING == 0x08
    assert FlowType.PING.value == 0x08
    assert FlowType.PAUSE == 0x16
    assert FlowType.PAUSE.value == 0x16
    assert FlowType.RESUME == 0x32
    assert FlowType.RESUME.value == 0x32
