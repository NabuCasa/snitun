"""Multiplexer message handling."""

import binascii
import os
from typing import NamedTuple
from functools import cached_property

import attr

CHANNEL_FLOW_NEW = 0x01
CHANNEL_FLOW_DATA = 0x02
CHANNEL_FLOW_CLOSE = 0x04
CHANNEL_FLOW_PING = 0x08

CHANNEL_FLOW_ALL = [
    CHANNEL_FLOW_NEW,
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_PING,
]


class MultiplexerChannelId(bytes):
    """Represent a channel ID aka multiplexer stream."""

    @cached_property
    def bytes(self) -> "bytes":
        """Return bytes representation of the channel ID."""
        return self

    @cached_property
    def hex(self) -> str:
        """Return hex representation of the channel ID."""
        return binascii.hexlify(self).decode("utf-8")

    def __str__(self) -> str:
        """Return string representation for logger."""
        return self.hex


class MultiplexerMessage(NamedTuple):
    """Represent a message from multiplexer stream."""

    id: MultiplexerChannelId
    flow_type: int  # one of CHANNEL_FLOW_ALL
    data: bytes = b""
    extra: bytes = b""
