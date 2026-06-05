"""An asyncio.Transport implementation for multiplexer channel."""

from __future__ import annotations

import asyncio
from asyncio import Transport
import logging
from typing import TYPE_CHECKING

from ..exceptions import MultiplexerTransportClose, MultiplexerTransportError
from ..multiplexer.channel import MultiplexerChannel
from ..utils.asyncio import create_eager_task
from .core import Multiplexer

_LOGGER = logging.getLogger(__name__)

# When the Cloud servers are able to get the real client IP
# this should be set to True so that the IP address can be
# used to block requests and passed to the end resource.
#
# This is useful to block requests from specific IP addresses
# and it means the client side will see the IP of the other
# end of the multiplexed connection for failed logins and other
# security features.
#
# If the Cloud servers are not able to get the real client IP
# this should be set to False so that the IP continues to present
# as 127.0.0.1
CHANNEL_IP_IS_CLIENT_IP = False

# Default maximum number of bytes to feed to the protocol at once.
# At runtime this is read from the protocol's max_size attribute
# (SSLProtocol sets this to 256 KiB). This fallback is only used
# if the protocol does not expose max_size.
_DEFAULT_READER_CHUNK_SIZE = 262144  # 256 KiB


def _feed_data_to_buffered_proto(proto: asyncio.BufferedProtocol, data: bytes) -> None:
    """Feed data to a buffered protocol.

    Adapted from asyncio.protocols
    https://github.com/python/cpython/blob/c1f352bf0813803bb795b796c16040a5cd4115f2/Lib/asyncio/protocols.py#L200-L226

    This function is used to feed data to a buffered protocol. It is
    used to handle the case where the protocol's buffer is smaller than
    the data to be fed to it.
    """
    data_len = len(data)
    while data_len:  # pragma: no branch
        buf = proto.get_buffer(data_len)
        buf_len = len(buf)  # type: ignore[arg-type]
        if not buf_len:
            raise RuntimeError("get_buffer() returned an empty buffer")

        if buf_len >= data_len:
            buf[:data_len] = data  # type: ignore[index]
            proto.buffer_updated(data_len)
            return

        buf[:buf_len] = data[:buf_len]  # type: ignore[index]
        proto.buffer_updated(buf_len)
        data = data[buf_len:]
        data_len = len(data)


class ChannelTransport(Transport):
    """An asyncio.Transport implementation for multiplexer channel.

    Replaces the loopback TCP connection by wrapping a MultiplexerChannel
    as an asyncio.Transport. This allows loop.start_tls() to layer
    SSLProtocol directly on top of the channel without an intermediate
    socket.

    After start_tls(), the protocol stack looks like:

        aiohttp RequestHandler  (app protocol)
               |
          SSLProtocol           (set as self._protocol by start_tls)
               |
        ChannelTransport        (this class)
               |
        MultiplexerChannel      (reads/writes multiplexed frames)

    Flow control — two directions:

    Writing (app -> channel):
        When the channel's output queue or the remote peer's input queue
        is under water, the MultiplexerChannel fires its
        pause_resume_reader_callback. ConnectorHandler translates that
        into pause_protocol() / resume_protocol() on this transport,
        which calls SSLProtocol.pause_writing() / resume_writing().
        This tells the app protocol to stop producing data.

    Reading (channel -> app):
        The _reader task reads from the channel and feeds data into
        SSLProtocol via _feed_data_to_buffered_proto. SSLProtocol can
        call pause_reading() / resume_reading() on this transport to
        throttle the reader when its internal BIO buffer is full.
    """

    # Required by loop.start_tls() to accept a non-socket transport.
    _start_tls_compatible = True

    def __init__(self, channel: MultiplexerChannel, multiplexer: Multiplexer) -> None:
        """Initialize ChannelTransport."""
        self._channel = channel
        self._loop = asyncio.get_running_loop()
        self._protocol: asyncio.BufferedProtocol | None = None
        self._pause_future: asyncio.Future[None] | None = None
        self._protocol_paused: bool = False
        self._reader_task: asyncio.Task[None] | None = None
        self._protocol_ready: asyncio.Future[None] = self._loop.create_future()
        self._protocol_set: bool = False
        self._multiplexer = multiplexer
        peername = str(channel.ip_address) if CHANNEL_IP_IS_CLIENT_IP else "127.0.0.1"
        super().__init__(extra={"peername": (peername, 0)})

    @property
    def protocol_paused(self) -> bool:
        """Return True if the protocol is paused."""
        return self._protocol_paused

    def start_reader(self) -> None:
        """Start the transport."""
        self._reader_task = create_eager_task(
            self._reader(),
            loop=self._loop,
            name=f"TransportReaderTask {self._channel.ip_address} ({self._channel.id})",
        )

    def get_protocol(self) -> asyncio.BufferedProtocol:
        """Return the protocol."""
        assert self._protocol is not None, (
            "ChannelTransport.get_protocol(): Protocol not set"
        )
        return self._protocol

    def set_protocol(self, protocol: asyncio.BaseProtocol | None) -> None:
        """Set the protocol."""
        assert isinstance(protocol, asyncio.BufferedProtocol), (
            "Protocol must be a BufferedProtocol"
        )
        self._protocol = protocol
        if not self._protocol_ready.done():
            self._protocol_set = True
            self._protocol_ready.set_result(None)

    def is_closing(self) -> bool:
        """Return True if the transport is closing or closed."""
        return self._channel.closing

    def close(self) -> None:
        """Close the underlying channel."""
        _LOGGER.debug(
            "Closing transport for %s (%s)",
            self._channel.ip_address,
            self._channel.id,
        )
        self._channel.close()
        self._release_pause_future()

    def abort(self) -> None:
        """Abort the transport immediately."""
        self.close()

    def write(self, data: bytes) -> None:
        """Write data to the channel."""
        if self._channel.closing:
            return
        try:
            self._channel.write_no_wait(data)
        except MultiplexerTransportClose:
            self._force_close(None)
        except MultiplexerTransportError as exc:
            self._force_close(exc)

    def resume_protocol(self) -> None:
        """Resume the protocol."""
        self._pause_or_resume_protocol(False)

    def pause_protocol(self) -> None:
        """Pause the protocol."""
        self._pause_or_resume_protocol(True)

    def _pause_or_resume_protocol(self, pause: bool) -> None:
        """Call a method on the protocol."""
        if not self._protocol or self.is_closing():
            return
        method_name = "pause_writing" if pause else "resume_writing"
        _LOGGER.debug(
            "Calling protocol.%s() for %s (%s)",
            method_name,
            self._channel.ip_address,
            self._channel.id,
        )
        try:
            if pause:
                self._protocol.pause_writing()
            else:
                self._protocol.resume_writing()
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:  # noqa: BLE001
            self._loop.call_exception_handler(
                {
                    "message": f"protocol.{method_name}() failed",
                    "exception": exc,
                    "transport": self,
                    "protocol": self._protocol,
                },
            )
        else:
            self._protocol_paused = pause

    async def wait_for_close(self) -> None:
        """Wait for the transport to close."""
        assert self._reader_task is not None, "Reader task not started"
        await self._reader_task

    async def _reader(self) -> None:
        """Read from the channel and pass data to the protocol."""
        chunk_size = 0
        while True:
            if self._pause_future:
                await self._pause_future

            try:
                from_peer = await self._channel.read()
            except MultiplexerTransportClose:
                self._force_close(None)
                return  # normal close
            except (SystemExit, KeyboardInterrupt):
                raise
            except BaseException as exc:
                self._fatal_error(exc, "Fatal error: channel.read() call failed.")
                raise

            if not self._protocol_set:
                await self._protocol_ready

            if TYPE_CHECKING:
                assert self._protocol is not None, "Protocol not set"

            if not chunk_size:
                # Use the protocol's buffer size as the chunk size.
                # For SSLProtocol, max_size (256 KiB) is the cap on
                # get_buffer() return size. Feeding data in chunks of
                # this size allows SSLProtocol's flow control to pause
                # us between chunks instead of overwhelming the BIO.
                chunk_size = getattr(
                    self._protocol,
                    "max_size",
                    _DEFAULT_READER_CHUNK_SIZE,
                )

            try:
                # Feed data in chunks to allow the event loop to process
                # SSLProtocol's flow control callbacks between chunks.
                # Without chunking, large messages overwhelm SSLProtocol
                # because _do_read() stops decrypting when the app
                # pauses reading.
                data = from_peer
                while data:
                    _feed_data_to_buffered_proto(
                        self._protocol,
                        data[:chunk_size],
                    )
                    data = data[chunk_size:]
                    if data and self._pause_future:
                        await self._pause_future
            except (SystemExit, KeyboardInterrupt):
                raise
            except BaseException as exc:
                self._fatal_error(
                    exc,
                    "Fatal error: consuming buffer or "
                    "protocol.buffer_updated() call failed.",
                )
                raise

    async def stop_reader(self) -> None:
        """Stop the transport."""
        assert self._reader_task is not None, "Reader task not started"
        self._reader_task.cancel()
        try:
            await self._reader_task
        except asyncio.CancelledError:
            # Don't swallow cancellation
            if (current_task := asyncio.current_task()) and current_task.cancelling():
                raise
        except Exception:
            _LOGGER.exception("Error in transport_reader_task")
        finally:
            self._reader_task = None

    def _force_close(self, exc: BaseException | None) -> None:
        """Force close the transport.

        Closes the channel and schedules connection_lost on the protocol
        (SSLProtocol after start_tls). The connection_lost call is
        required so SSLProtocol tears down promptly — without it,
        start_tls hangs waiting for handshake data that never arrives.

        Note: if aiohttp is serving a file via loop.sendfile() when the
        channel closes, _sendfile_fallback has temporarily swapped the
        app protocol on _SSLProtocolTransport. Our call_soon fires
        SSLProtocol.connection_lost() which sets _ssl_protocol = None,
        and the sendfile restore then hits AttributeError in
        _SSLProtocolTransport.set_protocol(). This is a CPython bug in
        _sendfile_fallback.restore() — it does not guard against the
        transport being torn down mid-transfer.
        """
        self.close()
        if self._protocol is not None and (exc is None or isinstance(exc, Exception)):
            self._loop.call_soon(self._protocol.connection_lost, exc)

    def _fatal_error(self, exc: BaseException, message: str) -> None:
        """Handle a fatal error."""
        self._loop.call_exception_handler(
            {
                "message": message,
                "exception": exc,
                "transport": self,
                "protocol": self._protocol,
            },
        )
        self._force_close(exc)

    def is_reading(self) -> bool:
        """Return True if the transport is receiving."""
        return self._pause_future is None

    def pause_reading(self) -> None:
        """Pause the receiving end.

        No data will be passed to the protocol's data_received()
        method until resume_reading() is called.
        """
        if self._pause_future is None:
            self._pause_future = self._loop.create_future()

    def resume_reading(self) -> None:
        """Resume the receiving end.

        Data received will once again be passed to the protocol's
        data_received() method.
        """
        self._release_pause_future()

    def _release_pause_future(self) -> None:
        """Release the pause future, if it exists.

        This will ensure that start can continue processing data.
        """
        if self._pause_future is not None and not self._pause_future.done():
            self._pause_future.set_result(None)
        self._pause_future = None
