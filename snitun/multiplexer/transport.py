"""An asyncio.Transport implementation for multiplexer channel."""

from __future__ import annotations

import asyncio
from asyncio import Transport
import asyncio.sslproto
import logging
import sys
from typing import TYPE_CHECKING

from ..exceptions import MultiplexerTransportClose
from ..multiplexer.channel import MultiplexerChannel
from ..utils.asyncio import create_eager_task
from .core import Multiplexer

_LOGGER = logging.getLogger(__name__)


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
    """An asyncio.Transport implementation for multiplexer channel."""

    _start_tls_compatible = True

    def __init__(self, channel: MultiplexerChannel, multiplexer: Multiplexer) -> None:
        """Initialize ChannelTransport."""
        self._channel = channel
        self._loop = asyncio.get_running_loop()
        self._protocol: asyncio.BufferedProtocol | None = None
        self._pause_future: asyncio.Future[None] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._multiplexer = multiplexer
        super().__init__(extra={"peername": (str(channel.ip_address), 0)})

    def start_reader(self) -> None:
        """Start the transport."""
        self._reader_task = create_eager_task(
            self._reader(),
            loop=self._loop,
            name=f"TransportReaderTask {self._channel.ip_address} ({self._channel.id})",
        )

    def get_protocol(self) -> asyncio.BufferedProtocol:
        """Return the protocol."""
        assert self._protocol is not None, "Protocol not set"
        return self._protocol

    def set_protocol(self, protocol: asyncio.BaseProtocol | None) -> None:
        """Set the protocol."""
        assert isinstance(protocol, asyncio.BufferedProtocol), (
            "Protocol must be a BufferedProtocol"
        )
        self._protocol = protocol

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

    def write(self, data: bytes) -> None:
        """Write data to the channel."""
        if not self._channel.closing:
            self._channel.write_no_wait(data)

    def resume_protocol(self) -> None:
        """Resume the protocol."""
        self._call_protocol_method("resume_writing")

    def pause_protocol(self) -> None:
        """Pause the protocol."""
        self._call_protocol_method("pause_writing")

    def _call_protocol_method(self, method_name: str) -> None:
        """Call a method on the protocol."""
        _LOGGER.debug(
            "Calling protocol.%s() for %s (%s)",
            method_name,
            self._channel.ip_address,
            self._channel.id,
        )
        try:
            getattr(self._protocol, method_name)()
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

    async def wait_for_close(self) -> None:
        """Wait for the transport to close."""
        assert self._reader_task is not None, "Reader task not started"
        await self._reader_task

    async def _reader(self) -> None:
        """Read from the channel and pass data to the protocol."""
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

            if TYPE_CHECKING:
                assert self._protocol is not None, "Protocol not set"

            try:
                _feed_data_to_buffered_proto(self._protocol, from_peer)
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
            if (
                sys.version_info >= (3, 11)
                and (current_task := asyncio.current_task())
                and current_task.cancelling()
            ):
                raise
        except Exception:
            _LOGGER.exception("Error in transport_reader_task")
        finally:
            self._reader_task = None

    def _force_close(self, exc: BaseException | None) -> None:
        """Force close the transport."""
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
