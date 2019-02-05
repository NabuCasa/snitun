"""Multiplexer message handling."""
import attr

CHANNEL_FLOW_NEW = 0x01
CHANNEL_FLOW_DATA = 0x02
CHANNEL_FLOW_CLOSE = 0x04
CHANNEL_FLOW_PING = 0x08

CHANNEL_FLOW_ALL = [
    CHANNEL_FLOW_NEW, CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA, CHANNEL_FLOW_PING
]


@attr.s(frozen=True)
class MultiplexerMessage:
    """Represent a message from multiplexer stream."""

    channel_id = attr.ib(type=str)
    flow_type = attr.ib(
        type=int, validator=attr.validators.in_(CHANNEL_FLOW_ALL))
    data = attr.ib(type=bytes, default=b"")
    extra = attr.ib(type=bytes, default=b"")
