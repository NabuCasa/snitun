"""Multiplexer message handling."""

from enum import IntEnum
from functools import cached_property, lru_cache
import struct
from typing import NamedTuple

MIN_PROTOCOL_VERSION_FOR_PAUSE_RESUME = 1


class FlowType(IntEnum):
    """Flow type for multiplexer message.

    Note that only one byte is available for the flow type.
    """

    NEW = 0x01  # protocol_version 0
    DATA = 0x02  # protocol_version 0
    CLOSE = 0x04  # protocol_version 0
    PING = 0x08  # protocol_version 0
    PAUSE = 0x16  # protocol_version 1
    RESUME = 0x32  # protocol_version 1

    @cached_property
    def value(self) -> int:
        """Return the value of the flow type."""
        return self._value_


CHANNEL_FLOW_NEW = FlowType.NEW.value
CHANNEL_FLOW_DATA = FlowType.DATA.value
CHANNEL_FLOW_CLOSE = FlowType.CLOSE.value
CHANNEL_FLOW_PING = FlowType.PING.value
CHANNEL_FLOW_PAUSE = FlowType.PAUSE.value
CHANNEL_FLOW_RESUME = FlowType.RESUME.value


# |-----------------HEADER---------------------------------|
# |------ID-----|--FLAG--|--SIZE--|---------EXTRA ---------|
# |   16 bytes  | 1 byte | 4 bytes|       11 bytes         |
# |--------------------------------------------------------|
# >:   All bytes are big-endian and unsigned
# 16s: 16 bytes: Channel ID - random
# B:   1 byte:   Flow type  - 1: NEW, 2: DATA, 4: CLOSE, 8: PING, 16: PAUSE, 32: RESUME
# I:   4 bytes:  Data size  - 0-4294967295
# 11s: 11 bytes: Extra      - data + random padding
HEADER_STRUCT = struct.Struct(">16sBI11s")
HEADER_SIZE = HEADER_STRUCT.size


class MultiplexerChannelId(bytes):
    """Represent a channel ID aka multiplexer stream."""

    @cached_property
    def bytes(self) -> "bytes":
        """Return bytes representation of the channel ID."""
        return self

    def __str__(self) -> str:
        """Return string representation for logger."""
        return self.hex()


@lru_cache
def try_parse_flow_type(flow_type: int) -> FlowType | int:
    """Try to parse flow type."""
    try:
        return FlowType(flow_type)
    except ValueError:
        return flow_type


class MultiplexerMessage(NamedTuple):
    """Represent a message from multiplexer stream."""

    id: MultiplexerChannelId
    flow_type: FlowType | int
    data: bytes = b""
    extra: bytes = b""

    def __repr__(self) -> str:
        """Return string representation for logger."""
        return (
            "MultiplexerMessage("
            f"id={self.id.hex()}, "
            f"flow_type={try_parse_flow_type(self.flow_type)!r}, "
            f"data={self.data!r}, "
            f"extra={self.extra!r}"
            ")"
        )
