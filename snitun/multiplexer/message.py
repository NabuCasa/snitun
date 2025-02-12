"""Multiplexer message handling."""

import binascii
from enum import IntFlag
from functools import cached_property
import struct
from typing import NamedTuple


class FlowType(IntFlag):
    """Flow type for multiplexer message."""

    NEW = 0x01
    DATA = 0x02
    CLOSE = 0x04
    PING = 0x08
    PAUSE = 0x16
    RESUME = 0x32

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
# B:   1 byte:   Flow type  - 1: NEW, 2: DATA, 4: CLOSE, 8: PING
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

    @cached_property
    def hex(self) -> str:  # type: ignore[override]
        """Return hex representation of the channel ID."""
        return binascii.hexlify(self).decode("utf-8")

    def __str__(self) -> str:
        """Return string representation for logger."""
        return self.hex


class MultiplexerMessage(NamedTuple):
    """Represent a message from multiplexer stream."""

    id: MultiplexerChannelId
    flow_type: FlowType
    data: bytes = b""
    extra: bytes = b""
