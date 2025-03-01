"""This file contains the constants used by the multiplexer."""

# When downloading a file, the message size will be
# ~4199990 bytes. Make sure we have enough space to store
# 16 messages in the incoming queue before we drop the connection.
INCOMING_QUEUE_MAX_BYTES_CHANNEL = 1024 * 1024 * 65
# Twice default value in asyncio transports to reduce
# the number of messages potentially being sent over
# the wire to pause or resume the channel.
# https://github.com/python/cpython/blob/75f38af7810af1c3ca567d6224a975f85aef970f/Lib/asyncio/transports.py#L319
INCOMING_QUEUE_HIGH_WATERMARK = 1024 * 128
INCOMING_QUEUE_LOW_WATERMARK = INCOMING_QUEUE_HIGH_WATERMARK // 4

OUTGOING_QUEUE_MAX_BYTES_CHANNEL = 1024 * 1024 * 12
# Same as default value in asyncio transports
# https://github.com/python/cpython/blob/75f38af7810af1c3ca567d6224a975f85aef970f/Lib/asyncio/transports.py#L319
OUTGOING_QUEUE_HIGH_WATERMARK = 1024 * 64
OUTGOING_QUEUE_LOW_WATERMARK = OUTGOING_QUEUE_HIGH_WATERMARK // 4

PEER_TCP_TIMEOUT = 90
