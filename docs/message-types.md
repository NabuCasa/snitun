# SniTun Multiplexer Message Types and Structures

This document describes all message types, wire formats, and protocol structures used in the SniTun multiplexer protocol.

---

## Wire Format Overview

Every multiplexer message consists of an **encrypted 32-byte header** optionally followed by **unencrypted payload data**. Headers are encrypted with AES-CBC (`snitun/multiplexer/crypto.py:10-34`). The payload (DATA messages) is transmitted in plaintext after the encrypted header.

```
|--- Encrypted Header (32 bytes) ---|--- Payload (0..N bytes) ---|
```

---

## Header Structure

Defined in `snitun/multiplexer/message.py:38-48`.

```
|-----------------HEADER---------------------------------|
|------ID-----|--FLAG--|--SIZE--|---------EXTRA ---------|
|   16 bytes  | 1 byte | 4 bytes|       11 bytes         |
|--------------------------------------------------------|
```

Packed with `struct.Struct(">16sBI11s")` (big-endian, unsigned):

| Field       | Size     | Format | Description                                                       |
|-------------|----------|--------|-------------------------------------------------------------------|
| Channel ID  | 16 bytes | `16s`  | Random UUID identifying the multiplexer channel/stream            |
| Flow Type   | 1 byte   | `B`    | Message type flag (see [Flow Types](#flow-types) below)           |
| Data Size   | 4 bytes  | `I`    | Length of the payload that follows the header (0 = no payload)    |
| Extra       | 11 bytes | `11s`  | Type-specific metadata, padded with random bytes for security     |

The Extra field is always padded to exactly 11 bytes with `os.urandom()` during serialization (`snitun/multiplexer/core.py:237`). This ensures the encrypted header is always a fixed 32 bytes regardless of how much extra data the message type actually needs.

---

## Flow Types

Defined as `FlowType` enum in `snitun/multiplexer/message.py:11-22`.

| Name     | Value  | Protocol Version | Description                              |
|----------|--------|------------------|------------------------------------------|
| `NEW`    | `0x01` | 0+               | Open a new multiplexer channel           |
| `DATA`   | `0x02` | 0+               | Transmit payload data through a channel  |
| `CLOSE`  | `0x04` | 0+               | Close/terminate a channel                |
| `PING`   | `0x08` | 0+               | Connection keep-alive ping/pong          |
| `PAUSE`  | `0x16` | 1+               | Flow control: pause sending data         |
| `RESUME` | `0x32` | 1+               | Flow control: resume sending data        |

Convenience constants are exported as `CHANNEL_FLOW_*` at `snitun/multiplexer/message.py:30-35`.

---

## Message Types in Detail

### 1. NEW (`0x01`) -- Open Channel

Creates a new multiplexer channel representing a proxied TCP connection.

**Sender:** The side initiating the proxied connection (via `MultiplexerChannel.init_new()` at `snitun/multiplexer/channel.py:285-290`).

**Extra field layout (5 bytes used, 6 bytes random padding):**

| Offset | Size   | Value                              |
|--------|--------|------------------------------------|
| 0      | 1 byte | `b"4"` (ASCII `0x34`) -- IPv4 flag |
| 1-4    | 4 bytes| IPv4 address of the originating client (packed with `inet_pton`) |
| 5-10   | 6 bytes| Random padding                     |

**Data:** None (data size = 0).

**Processing** (`snitun/multiplexer/core.py:302-317`):
- The receiver extracts the IP address from `extra[1:5]` using `bytes_to_ip_address()` (`snitun/utils/ipaddress.py:12-17`)
- A new `MultiplexerChannel` is created with the received channel ID and IP address
- The `new_connections` callback is invoked to handle the new channel

---

### 2. DATA (`0x02`) -- Transmit Data

Carries TCP payload data through an established channel.

**Sender:** Either side via `MultiplexerChannel.write()` at `snitun/multiplexer/channel.py:236-263`.

**Extra field:** Empty (`b""`), padded to 11 random bytes.

**Data:** The raw TCP payload bytes (1 to 4,294,967,295 bytes).

**Construction** (`snitun/multiplexer/channel.py:244-247`):
```python
message = tuple.__new__(
    MultiplexerMessage,
    (self._id, CHANNEL_FLOW_DATA, data, b""),
)
```

**Processing** (`snitun/multiplexer/core.py:282-299`):
- Verifies the channel exists and is healthy
- Unhealthy channels (input queue full) are closed
- Data is queued via `channel.message_transport(message)` (`snitun/multiplexer/channel.py:292-300`)
- The receiving side reads data via `MultiplexerChannel.read()` (`snitun/multiplexer/channel.py:265-277`)

---

### 3. CLOSE (`0x04`) -- Close Channel

Terminates an established multiplexer channel.

**Sender:** Either side via `Multiplexer.delete_channel()` at `snitun/multiplexer/core.py:391-403`, which calls `MultiplexerChannel.init_close()` at `snitun/multiplexer/channel.py:279-283`.

**Extra field:** Empty (`b""`), padded to 11 random bytes.

**Data:** None (data size = 0).

**Construction:**
```python
MultiplexerMessage(self._id, CHANNEL_FLOW_CLOSE)
```

**Processing** (`snitun/multiplexer/core.py:320-325`):
- Removes the channel from the active channels dict
- Deletes the channel's outgoing queue
- Calls `channel.close()` which enqueues a `None` sentinel on the input queue
- The `None` sentinel causes `MultiplexerChannel.read()` to raise `MultiplexerTransportClose`

---

### 4. PING (`0x08`) -- Keep-Alive

Bidirectional keep-alive mechanism to detect dead connections.

**Sender:** Either side via `Multiplexer.ping()` at `snitun/multiplexer/core.py:123-144`.

**Extra field:** Contains either `b"ping"` or `b"pong"` (padded to 11 bytes with random data).

**Data:** None (data size = 0).

**Ping request:**
```python
MultiplexerMessage(channel_id, CHANNEL_FLOW_PING, b"", b"ping")
```

**Pong response** (auto-generated at `snitun/multiplexer/core.py:334-336`):
```python
MultiplexerMessage(message.id, CHANNEL_FLOW_PING, b"", b"pong")
```

**Processing** (`snitun/multiplexer/core.py:328-336`):
- If `extra` starts with `b"pong"`: sets the `_healthy` event, unblocking the ping caller
- Otherwise: automatically responds with a pong message using the same channel ID
- Ping timeout is `PEER_TCP_TIMEOUT` (90 seconds, `snitun/multiplexer/const.py:69`)
- A timeout triggers `MultiplexerTransportError` and shuts down the connection

---

### 5. PAUSE (`0x16`) -- Flow Control Pause

Signals the remote side to stop sending data on a channel. Only available in protocol version >= 1 (`MIN_PROTOCOL_VERSION_FOR_PAUSE_RESUME = 1`, `snitun/multiplexer/message.py:8`).

**Sender:** Automatically sent when a channel's incoming queue crosses its high watermark (`snitun/multiplexer/channel.py:148-172`).

**Extra field:** Empty, padded to 11 random bytes.

**Data:** None (data size = 0).

**Construction:**
```python
MultiplexerMessage(self._id, CHANNEL_FLOW_PAUSE)
```

**Processing** (`snitun/multiplexer/core.py:339-351`):
- Calls `channel.on_remote_input_under_water(True)` (`snitun/multiplexer/channel.py:185-194`)
- Sets `_remote_input_under_water = True` on the channel
- Triggers `_pause_or_resume_reader()` which invokes the pause/resume callback to pause the TCP reader feeding data into this channel

---

### 6. RESUME (`0x32`) -- Flow Control Resume

Signals the remote side to resume sending data on a channel. Only available in protocol version >= 1.

**Sender:** Automatically sent when a channel's incoming queue drains below its low watermark (`snitun/multiplexer/channel.py:148-172`).

**Extra field:** Empty, padded to 11 random bytes.

**Data:** None (data size = 0).

**Construction:**
```python
MultiplexerMessage(self._id, CHANNEL_FLOW_RESUME)
```

**Processing** (`snitun/multiplexer/core.py:339-351`):
- Calls `channel.on_remote_input_under_water(False)` (`snitun/multiplexer/channel.py:185-194`)
- Sets `_remote_input_under_water = False` on the channel
- Triggers `_pause_or_resume_reader()` which invokes the pause/resume callback to resume the TCP reader

---

## Flow Control (Backpressure) Mechanism

Defined in `snitun/multiplexer/channel.py:130-207` and `snitun/multiplexer/const.py:1-67`.

Each channel tracks two independent backpressure signals:

1. **Local output under water** -- the outgoing multi-channel queue for this channel is full
2. **Remote input under water** -- the remote peer's incoming queue for this channel is full (signaled via PAUSE/RESUME messages)

Reading is paused if **either** condition is true, and resumed only when **both** are clear (`snitun/multiplexer/channel.py:196-207`).

### Queue Watermarks

**Incoming queue** (per-channel, `snitun/multiplexer/const.py:9-17`):

| Constant                               | Default     | Description                        |
|----------------------------------------|-------------|------------------------------------|
| `INCOMING_QUEUE_MAX_BYTES_CHANNEL`     | 65 MB       | Max queue size (protocol v1+)      |
| `INCOMING_QUEUE_MAX_BYTES_CHANNEL_V0`  | 256 MB      | Max queue size (protocol v0, no flow control) |
| `INCOMING_QUEUE_LOW_WATERMARK`         | 512 KB      | Resume threshold (send RESUME)     |
| `INCOMING_QUEUE_HIGH_WATERMARK`        | 2 MB        | Pause threshold (send PAUSE)       |

**Outgoing queue** (per-channel, `snitun/multiplexer/const.py:20-22`):

| Constant                               | Default     | Description                        |
|----------------------------------------|-------------|------------------------------------|
| `OUTGOING_QUEUE_MAX_BYTES_CHANNEL`     | 12 MB       | Max queue size                     |
| `OUTGOING_QUEUE_LOW_WATERMARK`         | 512 KB      | Resume threshold                   |
| `OUTGOING_QUEUE_HIGH_WATERMARK`        | 1 MB        | Pause threshold                    |

All queue constants are configurable via environment variables (see `snitun/multiplexer/const.py:24-67`).

---

## Protocol Versions

Defined in `snitun/utils/server.py:13-14`.

| Version | Constant                   | Features                                     |
|---------|----------------------------|----------------------------------------------|
| 0       | `DEFAULT_PROTOCOL_VERSION` | NEW, DATA, CLOSE, PING only. No flow control. Larger incoming queue (256 MB). |
| 1       | `PROTOCOL_VERSION`         | Adds PAUSE/RESUME flow control. Smaller incoming queue (65 MB). |

The protocol version is negotiated via the authentication token (`snitun/utils/server.py:17-49`). If a token omits `protocol_version`, the default (0) is assumed.

---

## Encryption

Defined in `snitun/multiplexer/crypto.py:10-34`.

- **Algorithm:** AES in CBC mode
- **Key/IV:** Provided via the authentication token (`aes_key` and `aes_iv` fields in `TokenData`, `snitun/utils/server.py:17-25`)
- **Scope:** Only the 32-byte header is encrypted. Payload data (in DATA messages) is transmitted in cleartext after the encrypted header.
- Encryption uses `cryptography.hazmat.primitives.ciphers` with `Cipher(AES(key), CBC(iv))`

---

## Serialization / Deserialization

### Writing (`snitun/multiplexer/core.py:229-245`)

1. Destructure the `MultiplexerMessage` into `(id, flow_type, data, extra)`
2. Pad `extra` to 11 bytes with `os.urandom(11 - len(extra))`
3. Pack header with `HEADER_STRUCT.pack(id.bytes, flow_type, len(data), padded_extra)`
4. Encrypt the 32-byte header with AES-CBC
5. Write encrypted header + raw data payload to the transport

### Reading (`snitun/multiplexer/core.py:247-276`)

1. Read exactly 32 bytes (one encrypted header) from the transport
2. Decrypt with AES-CBC
3. Unpack with `HEADER_STRUCT.unpack()` into `(channel_id, flow_type, data_size, extra)`
4. If `data_size > 0`, read exactly that many additional bytes as payload
5. Construct `MultiplexerMessage` and dispatch to `_process_message()`

---

## TLS/SNI Parsing Constants

Used for initial connection routing before multiplexer setup. Defined in `snitun/server/sni.py:13-15`.

| Constant                         | Value  | Description                           |
|----------------------------------|--------|---------------------------------------|
| `TLS_HEADER_LEN`                | 5      | Size of a TLS record header           |
| `TLS_HANDSHAKE_CONTENT_TYPE`    | `0x16` | TLS ContentType for Handshake records |
| `TLS_HANDSHAKE_TYPE_CLIENT_HELLO` | `0x01` | HandshakeType for ClientHello       |

These are used by `parse_tls_sni()` (`snitun/server/sni.py:47-105`) to extract the hostname from a TLS ClientHello SNI extension, which determines which peer should handle the connection.

---

## Core Data Types

### `MultiplexerMessage` (`snitun/multiplexer/message.py:73-90`)

```python
class MultiplexerMessage(NamedTuple):
    id: MultiplexerChannelId       # 16-byte channel identifier
    flow_type: FlowType | int     # Message type (FlowType enum value)
    data: bytes = b""             # Payload (only for DATA messages)
    extra: bytes = b""            # Type-specific metadata
```

### `MultiplexerChannelId` (`snitun/multiplexer/message.py:51-61`)

```python
class MultiplexerChannelId(bytes):
    # 16-byte random identifier for a channel/stream
    # Displayed as hex string in logs
```

### `TokenData` (`snitun/utils/server.py:17-25`)

```python
class TokenData(TypedDict):
    valid: float                           # Expiration timestamp
    hostname: str                          # Target hostname
    aes_key: str                           # Hex-encoded AES key
    aes_iv: str                            # Hex-encoded AES IV
    protocol_version: NotRequired[int]     # Protocol version (default 0)
    alias: list[str] | None               # Hostname aliases
```

---

## Exception Hierarchy

Defined in `snitun/exceptions.py:1-38`.

```
SniTunError
├── SniTunChallengeError          # Authentication challenge failure
├── SniTunInvalidPeer             # Invalid peer configuration
├── SniTunConnectionError         # Connection failure
├── ParseSNIError                 # Invalid TLS ClientHello
│   └── ParseSNIIncompleteError   # Incomplete TLS data (need more bytes)
├── MultiplexerTransportError     # General multiplexer transport problem
├── MultiplexerTransportClose     # Multiplexer connection closed
└── MultiplexerTransportDecrypt   # Header decryption failure
```
