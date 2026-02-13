"""This file contains the constants used by the multiplexer."""

import os

# When downloading a file, the message size will be
# ~4199990 bytes which is the protocol maximum. Make
# sure we have enough space to store 16 messages
# in the incoming queue before we drop the connection.
DEFAULT_INCOMING_QUEUE_MAX_BYTES_CHANNEL = 1024 * 1024 * 65
DEFAULT_INCOMING_QUEUE_LOW_WATERMARK = 1024 * 512
DEFAULT_INCOMING_QUEUE_HIGH_WATERMARK = 1024 * 1024 * 2

# For protocol version 0, there is no flow control
# and the incoming queue is much larger to accommodate
# the fact we can't tell the client to pause/resume reading.
# This is a temporary solution until we can remove protocol version 0.
DEFAULT_INCOMING_QUEUE_MAX_BYTES_CHANNEL_V0 = 1024 * 1024 * 256


DEFAULT_OUTGOING_QUEUE_MAX_BYTES_CHANNEL = 1024 * 1024 * 12
DEFAULT_OUTGOING_QUEUE_LOW_WATERMARK = 1024 * 512
DEFAULT_OUTGOING_QUEUE_HIGH_WATERMARK = 1024 * 1024 * 1

INCOMING_QUEUE_MAX_BYTES_CHANNEL = int(
    os.getenv(
        "MULTIPLEXER_INCOMING_QUEUE_MAX_BYTES_CHANNEL",
        DEFAULT_INCOMING_QUEUE_MAX_BYTES_CHANNEL,
    ),
)
INCOMING_QUEUE_LOW_WATERMARK = int(
    os.getenv(
        "MULTIPLEXER_INCOMING_QUEUE_LOW_WATERMARK",
        DEFAULT_INCOMING_QUEUE_LOW_WATERMARK,
    ),
)
INCOMING_QUEUE_HIGH_WATERMARK = int(
    os.getenv(
        "MULTIPLEXER_INCOMING_QUEUE_HIGH_WATERMARK",
        DEFAULT_INCOMING_QUEUE_HIGH_WATERMARK,
    ),
)

INCOMING_QUEUE_MAX_BYTES_CHANNEL_V0 = int(
    os.getenv(
        "MULTIPLEXER_INCOMING_QUEUE_MAX_BYTES_CHANNEL_V0",
        DEFAULT_INCOMING_QUEUE_MAX_BYTES_CHANNEL_V0,
    ),
)

OUTGOING_QUEUE_MAX_BYTES_CHANNEL = int(
    os.getenv(
        "MULTIPLEXER_OUTGOING_QUEUE_MAX_BYTES_CHANNEL",
        DEFAULT_OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
    ),
)
OUTGOING_QUEUE_LOW_WATERMARK = int(
    os.getenv(
        "MULTIPLEXER_OUTGOING_QUEUE_LOW_WATERMARK",
        DEFAULT_OUTGOING_QUEUE_LOW_WATERMARK,
    ),
)
OUTGOING_QUEUE_HIGH_WATERMARK = int(
    os.getenv(
        "MULTIPLEXER_OUTGOING_QUEUE_HIGH_WATERMARK",
        DEFAULT_OUTGOING_QUEUE_HIGH_WATERMARK,
    ),
)

PEER_TCP_TIMEOUT = 90
