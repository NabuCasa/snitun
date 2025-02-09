"""Multiplexer message handling."""

import binascii
from functools import cached_property
import os

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


@attr.s(frozen=True, eq=True, hash=True, cache_hash=True)
class MultiplexerChannelId:
    """Represent a channel ID aka multiplexer stream."""

    bytes: "bytes" = attr.ib(default=attr.Factory(lambda: os.urandom(16)), eq=True)

    @cached_property
    def hex(self) -> str:
        """Return hex representation of the channel ID."""
        return binascii.hexlify(self.bytes).decode("utf-8")

    def __str__(self) -> str:
        """Return string representation for logger."""
        return self.hex


@attr.s(frozen=True, slots=True)
class MultiplexerMessage:
    """Represent a message from multiplexer stream."""

    id: MultiplexerChannelId = attr.ib()
    flow_type: int = attr.ib(validator=attr.validators.in_(CHANNEL_FLOW_ALL))
    data: bytes = attr.ib(default=b"")
    extra: bytes = attr.ib(default=b"")
