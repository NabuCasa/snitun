"""This file contains the constants used by the multiplexer."""

# When downloading a file, the message size will be
# ~4199990 bytes which is the protocol maximum. Make
# sure we have enough space to store 16 messages
# in the incoming queue before we drop the connection.
INCOMING_QUEUE_MAX_BYTES_CHANNEL = 1024 * 1024 * 65
INCOMING_QUEUE_LOW_WATERMARK = 1024 * 1024 * 1
INCOMING_QUEUE_HIGH_WATERMARK = 1024 * 1024 * 2

OUTGOING_QUEUE_MAX_BYTES_CHANNEL = 1024 * 1024 * 12
OUTGOING_QUEUE_LOW_WATERMARK = 1024 * 1024 * 2
OUTGOING_QUEUE_HIGH_WATERMARK = 1024 * 1024 * 4

PEER_TCP_TIMEOUT = 90
