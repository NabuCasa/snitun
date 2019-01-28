"""Multiplexer message handling."""

import attr

PROTO_FLOW_NEW = 0x01
PROTO_FLOW_DATA = 0x02
PROTO_FLOW_CLOSE = 0x04

PROTO_FLOW_ALL = [PROTO_FLOW_NEW, PROTO_FLOW_CLOSE, PROTO_FLOW_DATA]


@attr.s(frozen=True)
class MultiplexerMessage:
    """Represent a message from multiplexer stream."""

    session_id = attr.ib(type=str)
    flow_type = attr.ib(type=int, validator=attr.validators.in_(PROTO_FLOW_ALL))
    data = attr.ib(type=bytes)
