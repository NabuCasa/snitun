"""This file contains the constants used by the multiplexer."""

import struct

INCOMING_QUEUE_MAX_BYTES_CHANNEL = 1024 * 1024 * 10
OUTGOING_QUEUE_MAX_BYTES_CHANNEL = 1024 * 1024 * 12

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

PEER_TCP_TIMEOUT = 90
